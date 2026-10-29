import frappe
from frappe.utils import flt

from frappe_livestock.api.allocation import split_purchase_to_flocks
from frappe_livestock.api.purchase import create_full_purchase


def _chick_lines(flock_doc, purchase_invoice):
	"""The lines of `purchase_invoice` that sell the flock type's chick_item."""
	livestock_type = frappe.get_doc("Livestock Type", flock_doc.livestock_type)
	if not livestock_type.chick_item:
		frappe.throw(frappe._("Set a Chick Item on Livestock Type {0} first.").format(livestock_type.name))

	invoice = frappe.get_doc("Purchase Invoice", purchase_invoice)
	if invoice.docstatus != 1:
		frappe.throw(frappe._("Purchase Invoice {0} is not submitted.").format(invoice.name))

	lines = [row for row in invoice.items if row.item_code == livestock_type.chick_item]
	if not lines:
		frappe.throw(
			frappe._("Purchase Invoice {0} has no {1} line to allocate.").format(
				invoice.name, frappe.bold(livestock_type.chick_item)
			)
		)
	return lines


def _allocate_to_flock(flock_name, purchase_invoice):
	"""Allocate an invoice's chick lines to one flock (idempotent upsert) and
	link the invoice on the flock. Same cost mechanism as feed: Flock Cost rows."""
	flock_doc = frappe.get_doc("Flock", flock_name)
	lines = _chick_lines(flock_doc, purchase_invoice)

	split_purchase_to_flocks(
		purchase_invoice,
		[{"item_code": row.item_code, "flock": flock_name, "qty": row.qty} for row in lines],
	)

	if flock_doc.chick_purchase_invoice != purchase_invoice:
		frappe.db.set_value(
			"Flock", flock_name, "chick_purchase_invoice", purchase_invoice, update_modified=False
		)

	return {"flock": flock_name, "purchase_invoice": purchase_invoice}


@frappe.whitelist()
def link_chick_purchase(flock, purchase_invoice):
	"""Link an existing (already-paid) chick purchase to a flock and allocate
	its chick lines as the flock's initial cost."""
	return _allocate_to_flock(flock, purchase_invoice)


@frappe.whitelist()
def create_chick_purchase(
	flock,
	supplier,
	warehouse,
	rate,
	company=None,
	invoice_date=None,
	mode_of_payment="Cash",
	invoice_number=None,
):
	"""Buy the flock's day-old chicks in one action: full purchase chain for
	`quantity_placed` chicks of the type's chick_item at `rate` each, paid in
	full on the spot, then allocated to the flock as its initial cost."""
	flock_doc = frappe.get_doc("Flock", flock)
	livestock_type = frappe.get_doc("Livestock Type", flock_doc.livestock_type)
	if not livestock_type.chick_item:
		frappe.throw(frappe._("Set a Chick Item on Livestock Type {0} first.").format(livestock_type.name))

	rate = flt(rate)
	if rate < 0:
		frappe.throw(frappe._("Rate must be 0 or greater."))

	company = company or frappe.defaults.get_user_default("Company")

	# reuse the full purchase chain (PO -> Receipt -> Invoice -> Payment)
	made = create_full_purchase(
		company=company,
		supplier=supplier,
		warehouse=warehouse,
		items=[{"item_code": livestock_type.chick_item, "qty": flock_doc.quantity_placed, "rate": rate}],
		invoice_number=invoice_number,
		invoice_date=invoice_date,
		mode_of_payment=mode_of_payment,
	)

	return _allocate_to_flock(flock, made["purchase_invoice"])
