import frappe
from frappe.utils import flt


def _invoice_rates(purchase_invoice):
	rows = frappe.db.sql(
		"select item_code, rate from `tabPurchase Invoice Item` where parent = %s",
		purchase_invoice,
		as_dict=True,
	)
	return {row["item_code"]: float(row["rate"] or 0) for row in rows}


def _row_key(row):
	"""Identity of a Batch Cost row for overwrite comparison.

	Amount is deliberately excluded: freshly computed float amounts
	(e.g. rate 1.2 x qty 3 = 3.5999999999999996) never equal the
	DB-decimal rounded value (3.6), so including amount makes identical
	re-runs look "different". Identity = (item_code, batch, qty).
	"""
	if isinstance(row, dict):
		item_code, batch, qty = (
			row.get("item_code"),
			row.get("batch"),
			row.get("qty"),
		)
	else:
		item_code, batch, qty = row.item_code, row.batch, row.qty
	return (item_code, batch, flt(qty))


@frappe.whitelist()
def split_purchase_to_batches(purchase_invoice, allocations, force=None):
	"""Split a bulk purchase invoice across batches, deriving amount from PI line rates.

	args:
	        purchase_invoice: Name of the source Purchase Invoice
	        allocations: List of {item_code, qty, batch} dicts (JSON-encoded when called over HTTP)
	        force: Overwrite an existing Batch Cost only when its stored rows differ
	                AND this is truthy (JSON-parsed bool). Identical rows upsert
	                silently (idempotent); a forced overwrite leaves an audit Comment.
	"""
	allocations = frappe.parse_json(allocations) or []
	if isinstance(force, str):
		try:
			force = frappe.parse_json(force) if force.strip() else None
		except Exception:
			frappe.throw("force must be a boolean")
	if not purchase_invoice:
		frappe.throw("purchase_invoice is required")
	if not allocations or not isinstance(allocations, list):
		frappe.throw("At least one allocation is required")

	rates = _invoice_rates(purchase_invoice)
	rows = []
	for allocation in allocations:
		item_code = allocation.get("item_code")
		qty = float(allocation.get("qty") or 0)
		batch = allocation.get("batch")
		if item_code not in rates:
			frappe.throw(f"Item '{item_code}' is not on Purchase Invoice '{purchase_invoice}'")
		if qty <= 0:
			frappe.throw(f"qty must be greater than 0 for item '{item_code}'")
		if not batch or not frappe.db.exists("Livestock Batch", batch):
			frappe.throw(f"Livestock Batch '{batch}' does not exist")
		if frappe.db.get_value("Livestock Batch", batch, "status") == "Closed":
			frappe.throw(f"Batch {batch} is closed")
		rows.append(
			{
				"item_code": item_code,
				"qty": qty,
				"amount": rates[item_code] * qty,
				"batch": batch,
			}
		)

	existing = frappe.db.exists("Batch Cost", {"purchase_invoice": purchase_invoice})
	if existing:
		doc = frappe.get_doc("Batch Cost", existing)
		old_keys = sorted(_row_key(row) for row in doc.items)
		new_keys = sorted(_row_key(row) for row in rows)
		if old_keys != new_keys:
			if not force:
				frappe.throw(
					f"Batch Cost {doc.name} already exists with different rows. Confirm overwrite to proceed."
				)
			old_total = flt(sum(flt((row.amount if hasattr(row, 'amount') else row.get('amount')) or 0) for row in doc.items), 2)
			new_total = flt(sum(flt(row.get('amount') or 0) for row in rows), 2)
			frappe.get_doc(
				{
					"doctype": "Comment",
					"comment_type": "Comment",
					"reference_doctype": "Batch Cost",
					"reference_name": doc.name,
					"content": (
						f"Rows replaced: {len(old_keys)} rows ({old_total} amount) → "
						f"{len(new_keys)} rows ({new_total} amount) by {frappe.session.user}"
					),
				}
			).insert()
		doc.set("items", [])
		for row in rows:
			doc.append("items", row)
		doc.save()
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Batch Cost",
				"purchase_invoice": purchase_invoice,
				"items": rows,
			}
		).insert()

	return {"batch_cost": doc.name, "items": len(doc.items)}


@frappe.whitelist()
def get_active_batches():
	"""Return non-closed batches newest first as {name, start_date, remaining} dicts."""
	names = frappe.db.sql(
		"select name from `tabLivestock Batch` where status != 'Closed' order by start_date desc",
		pluck=True,
	)
	return [
		{
			"name": name,
			"start_date": frappe.db.get_value("Livestock Batch", name, "start_date"),
			"remaining": frappe.get_doc("Livestock Batch", name).remaining(),
		}
		for name in names
	]
