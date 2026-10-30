import frappe
from frappe.utils import flt

from frappe_livestock.api.allocation import split_purchase_to_batches
from frappe_livestock.api.purchase import create_full_purchase


def _stocking_lines(batch_doc, purchase_invoice):
	"""The lines of `purchase_invoice` that sell the batch type's stocking_item."""
	livestock_type = frappe.get_doc("Livestock Type", batch_doc.livestock_type)
	if not livestock_type.stocking_item:
		frappe.throw(frappe._("Set a Stocking Item on Livestock Type {0} first.").format(livestock_type.name))

	invoice = frappe.get_doc("Purchase Invoice", purchase_invoice)
	if invoice.docstatus != 1:
		frappe.throw(frappe._("Purchase Invoice {0} is not submitted.").format(invoice.name))

	lines = [row for row in invoice.items if row.item_code == livestock_type.stocking_item]
	if not lines:
		frappe.throw(
			frappe._("Purchase Invoice {0} has no {1} line to allocate.").format(
				invoice.name, frappe.bold(livestock_type.stocking_item)
			)
		)
	return lines


def _allocate_to_batch(batch_name, purchase_invoice):
	"""Allocate an invoice's stocking lines to one batch (idempotent upsert) and
	link the invoice on the batch. Same cost mechanism as feed: Batch Cost rows."""
	batch_doc = frappe.get_doc("Livestock Batch", batch_name)
	lines = _stocking_lines(batch_doc, purchase_invoice)

	split_purchase_to_batches(
		purchase_invoice,
		[{"item_code": row.item_code, "batch": batch_name, "qty": row.qty} for row in lines],
	)

	if batch_doc.stocking_purchase_invoice != purchase_invoice:
		frappe.db.set_value(
			"Livestock Batch", batch_name, "stocking_purchase_invoice", purchase_invoice, update_modified=False
		)

	return {"batch": batch_name, "purchase_invoice": purchase_invoice}


@frappe.whitelist()
def link_stocking_purchase(batch, purchase_invoice):
	"""Link an existing (already-paid) stocking purchase to a batch and allocate
	its stocking lines as the batch's initial cost."""
	return _allocate_to_batch(batch, purchase_invoice)


@frappe.whitelist()
def create_stocking_purchase(
	batch,
	supplier,
	warehouse,
	rate,
	company=None,
	invoice_date=None,
	mode_of_payment="Cash",
	invoice_number=None,
):
	"""Buy the batch's stocking stock in one action: full purchase chain for
	`quantity_placed` head of stock of the type's stocking_item at `rate` each, paid in
	full on the spot, then allocated to the batch as its initial cost."""
	batch_doc = frappe.get_doc("Livestock Batch", batch)
	livestock_type = frappe.get_doc("Livestock Type", batch_doc.livestock_type)
	if not livestock_type.stocking_item:
		frappe.throw(frappe._("Set a Stocking Item on Livestock Type {0} first.").format(livestock_type.name))

	rate = flt(rate)
	if rate < 0:
		frappe.throw(frappe._("Rate must be 0 or greater."))

	company = company or frappe.defaults.get_user_default("Company")

	# reuse the full purchase chain (PO -> Receipt -> Invoice -> Payment)
	made = create_full_purchase(
		company=company,
		supplier=supplier,
		warehouse=warehouse,
		items=[{"item_code": livestock_type.stocking_item, "qty": batch_doc.quantity_placed, "rate": rate}],
		invoice_number=invoice_number,
		invoice_date=invoice_date,
		mode_of_payment=mode_of_payment,
	)

	return _allocate_to_batch(batch, made["purchase_invoice"])
