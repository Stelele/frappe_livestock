import frappe
from frappe.utils import flt


def allocate_sales_to_ready_flocks_for_type(flock_type, qty, sales_invoice=None, rate=None):
	"""Allocate `qty` finished-bird units to Ready flocks of `flock_type`, oldest first.

	Each flock absorbs min(qty_remaining, surviving_birds - birds_sold); only
	`birds_sold` is incremented (status untouched). Returns
	`{"allocated", "unallocated"}` where `unallocated` is the shortfall that
	did not fit inside any Ready flock's surviving ceiling.

	When `sales_invoice` is given, the per-flock allocation is recorded in the
	invoice's Flock Sale ledger (rows keyed by flock; re-runs replace rows for
	the same flocks instead of double-counting) — that ledger is what the
	reporting API reads revenue from.
	"""
	qty = int(qty or 0)
	if not flock_type or qty <= 0:
		return {"allocated": 0, "unallocated": max(qty, 0)}

	rows = frappe.db.get_list(
		"Flock",
		filters={"livestock_type": flock_type, "status": "Ready"},
		fields=["name"],
		order_by="start_date asc",
		ignore_permissions=True,  # R16: hook runs as the submitting user (e.g. Sales User),
		# who has no Flock read permission; allocation must still see Ready flocks.
	)

	allocated = 0
	remaining = qty
	allocated_per_flock = {}
	for row in rows:
		if remaining <= 0:
			break
		flock = frappe.get_doc("Flock", row["name"])  # read-only: ceiling only
		ceiling = flock.surviving_birds() - int(flock.birds_sold or 0)
		if ceiling <= 0:
			continue
		take = min(remaining, ceiling)
		# R16: elevated counter write — bypasses the doc write-permission gate
		# so a non-admin submitter never blocks; touches only `birds_sold`.
		frappe.db.set_value(
			"Flock",
			row["name"],
			"birds_sold",
			int(flock.birds_sold or 0) + take,
			update_modified=False,
		)
		allocated += take
		remaining -= take
		allocated_per_flock[row["name"]] = allocated_per_flock.get(row["name"], 0) + take

	if sales_invoice and allocated_per_flock:
		_record_flock_sale(flock_type, sales_invoice, allocated_per_flock, rate)

	return {"allocated": allocated, "unallocated": remaining}


def _record_flock_sale(flock_type, sales_invoice, allocated_per_flock, rate=None):
	"""Upsert the invoice's Flock Sale ledger with this allocation's rows.

	Multiple seam calls can contribute to one invoice (one per flock type /
	rate group); rows are keyed by (item_code, flock) — re-allocated flocks
	replace their row, others are kept."""
	item_to_type = _finished_item_to_type()
	finished_item = next(
		(item for item, ftype in item_to_type.items() if ftype == flock_type), None
	)
	if not finished_item:
		return

	existing = frappe.db.exists("Flock Sale", sales_invoice)
	if existing:
		sale = frappe.get_doc("Flock Sale", sales_invoice)
	else:
		sale = frappe.new_doc("Flock Sale")
		sale.sales_invoice = sales_invoice
		sale.posting_date = frappe.db.get_value("Sales Invoice", sales_invoice, "posting_date")

	for flock_name, qty in allocated_per_flock.items():
		sale.items = [row for row in sale.items if not (row.item_code == finished_item and row.flock == flock_name)]
		sale.append(
			"items",
			{
				"item_code": finished_item,
				"flock": flock_name,
				"qty": qty,
				"amount": flt(qty) * flt(rate or 0),
			},
		)

	sale.save(ignore_permissions=True)  # R16: the submitting user may lack Flock Sale write


def _finished_item_to_type():
	"""Map Livestock Type `finished_item` -> livestock type name."""
	rows = frappe.db.get_all(
		"Livestock Type", filters={"finished_item": ["!=", ""]}, fields=["name", "finished_item"]
	)
	return {row["finished_item"]: row["name"] for row in rows if row.get("finished_item")}


def _allocate_invoice_items(items, sales_invoice=None):
	"""Sum invoice-item qtys per (flock type, rate) and allocate via the seam.

	Grouping by rate keeps recorded revenue exact when an invoice carries the
	same finished item at two rates."""
	item_to_type = _finished_item_to_type()
	groups = {}
	for item in items or []:
		item_code = item.get("item_code") if isinstance(item, dict) else item.item_code
		qty = item.get("qty") if isinstance(item, dict) else item.qty
		item_rate = (item.get("rate") if isinstance(item, dict) else item.rate) or 0
		flock_type = item_to_type.get(item_code)
		if not flock_type:
			continue
		key = (flock_type, flt(item_rate))
		groups[key] = groups.get(key, 0) + int(qty or 0)

	allocated = 0
	unallocated = 0
	for (flock_type, rate), qty in groups.items():
		result = allocate_sales_to_ready_flocks_for_type(
			flock_type=flock_type, qty=qty, sales_invoice=sales_invoice, rate=rate
		)
		allocated += result["allocated"]
		unallocated += result["unallocated"]
	return {"allocated": allocated, "unallocated": unallocated}


def allocate_sales_to_ready_flocks(doc=None, method=None):
	"""Hook entry: Sales Invoice on_submit -> FIFO sale allocation to Ready flocks.

	Called positionally as `allocate_sales_to_ready_flocks(doc, method)` by the
	`doc_events` hook. When `doc` is a Sales Invoice document (or name), only
	that invoice's lines are processed. A `None` doc is an explicit no-op
	(phase-2 park: a no-arg sweep would need an allocation ledger to stay
	idempotent; the on_submit hook is the auto path).
	Returns `{"allocated", "unallocated"}`.
	"""
	if doc is None:
		return {"allocated": 0, "unallocated": 0}

	if isinstance(doc, str):
		doc = frappe.get_doc("Sales Invoice", doc)
	return _allocate_invoice_items(doc.items, sales_invoice=doc.name)


def revoke_sale_allocation(doc=None, method=None):
	"""Hook entry: Sales Invoice on_cancel -> undo that invoice's allocation.

	Decrements each flock's `birds_sold` by its recorded Flock Sale rows (floored
	at 0 — manual corrections are allowed to have moved the number) and deletes
	the invoice's Flock Sale ledger so cancelled revenue never reports."""
	if doc is None:
		return {"revoked": 0}
	if isinstance(doc, str):
		doc = frappe.get_doc("Sales Invoice", doc)

	if not frappe.db.exists("Flock Sale", doc.name):
		return {"revoked": 0}

	sale = frappe.get_doc("Flock Sale", doc.name)
	revoked = 0
	for row in sale.items:
		current = int(frappe.db.get_value("Flock", row.flock, "birds_sold") or 0)
		frappe.db.set_value(
			"Flock", row.flock, "birds_sold", max(current - int(row.qty or 0), 0), update_modified=False
		)
		revoked += int(row.qty or 0)

	frappe.delete_doc("Flock Sale", doc.name, ignore_permissions=True)
	return {"revoked": revoked}
