import frappe


def allocate_sales_to_ready_flocks_for_type(flock_type, qty):
	"""Allocate `qty` finished-bird units to Ready flocks of `flock_type`, oldest first.

	Each flock absorbs min(qty_remaining, surviving_birds - birds_sold); only
	`birds_sold` is incremented (status untouched). Returns
	`{"allocated", "unallocated"}` where `unallocated` is the shortfall that
	did not fit inside any Ready flock's surviving ceiling.
	"""
	qty = int(qty or 0)
	if not flock_type or qty <= 0:
		return {"allocated": 0, "unallocated": max(qty, 0)}

	rows = frappe.db.get_list(
		"Flock",
		filters={"livestock_type": flock_type, "status": "Ready"},
		fields=["name"],
		order_by="start_date asc",
	)

	allocated = 0
	remaining = qty
	for row in rows:
		if remaining <= 0:
			break
		flock = frappe.get_doc("Flock", row["name"])
		ceiling = flock.surviving_birds() - int(flock.birds_sold or 0)
		if ceiling <= 0:
			continue
		take = min(remaining, ceiling)
		flock.birds_sold = int(flock.birds_sold or 0) + take
		flock.save()
		allocated += take
		remaining -= take

	return {"allocated": allocated, "unallocated": remaining}


def _finished_item_to_type():
	"""Map Livestock Type `finished_item` -> livestock type name."""
	rows = frappe.db.get_all(
		"Livestock Type", filters={"finished_item": ["!=", ""]}, fields=["name", "finished_item"]
	)
	return {row["finished_item"]: row["name"] for row in rows if row.get("finished_item")}


def _allocate_invoice_items(items):
	"""Sum invoice-item qtys per flock type and allocate via the seam."""
	item_to_type = _finished_item_to_type()
	qty_per_type = {}
	for item in items or []:
		item_code = item.get("item_code") if isinstance(item, dict) else item.item_code
		qty = item.get("qty") if isinstance(item, dict) else item.qty
		flock_type = item_to_type.get(item_code)
		if not flock_type:
			continue
		qty_per_type[flock_type] = qty_per_type.get(flock_type, 0) + int(qty or 0)

	allocated = 0
	unallocated = 0
	for flock_type, qty in qty_per_type.items():
		result = allocate_sales_to_ready_flocks_for_type(flock_type=flock_type, qty=qty)
		allocated += result["allocated"]
		unallocated += result["unallocated"]
	return {"allocated": allocated, "unallocated": unallocated}


def allocate_sales_to_ready_flocks(doc=None, method=None):
	"""Hook entry: Sales Invoice on_submit -> FIFO sale allocation to Ready flocks.

	Called positionally as `allocate_sales_to_ready_flocks(doc, method)` by the
	`doc_events` hook. When `doc` is a Sales Invoice document (or name), only
	that invoice's lines are processed; when `doc` is None, recent submitted
	Sales Invoices are processed. Returns `{"allocated", "unallocated"}`.
	"""
	if doc is None:
		names = frappe.db.get_list(
			"Sales Invoice", filters={"docstatus": 1}, pluck="name", order_by="modified desc", limit=100
		)
		allocated = 0
		unallocated = 0
		for name in names:
			result = _allocate_invoice_items(frappe.get_doc("Sales Invoice", name).items)
			allocated += result["allocated"]
			unallocated += result["unallocated"]
		return {"allocated": allocated, "unallocated": unallocated}

	if isinstance(doc, str):
		doc = frappe.get_doc("Sales Invoice", doc)
	return _allocate_invoice_items(doc.items)
