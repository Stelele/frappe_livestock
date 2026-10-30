import frappe


def _invoice_rates(purchase_invoice):
	rows = frappe.db.sql(
		"select item_code, rate from `tabPurchase Invoice Item` where parent = %s",
		purchase_invoice,
		as_dict=True,
	)
	return {row["item_code"]: float(row["rate"] or 0) for row in rows}


@frappe.whitelist()
def split_purchase_to_batches(purchase_invoice, allocations):
	"""Split a purchase's lines across batches (JSON-encoded allocations over HTTP)."""
	allocations = frappe.parse_json(allocations) or []
	"""Split a bulk purchase invoice across batches, deriving amount from PI line rates.

	args:
	        purchase_invoice: Name of the source Purchase Invoice
	        allocations: List of {item_code, qty, batch} dicts
	"""
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
