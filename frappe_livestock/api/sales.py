import frappe
from frappe.utils import flt, today


def allocate_sales_to_ready_batches_for_type(batch_type, qty, voucher_type=None, voucher_no=None, rate=None):
	"""Allocate `qty` finished-bird units to Ready batches of `batch_type`, oldest first.

	Each batch absorbs min(qty_remaining, surviving - sold); only
	`sold` is incremented (status untouched). Returns
	`{"allocated", "unallocated"}` where `unallocated` is the shortfall that
	did not fit inside any Ready batch's surviving ceiling.

	When `voucher_no` is given, the per-batch allocation is recorded in the
	invoice's Batch Sale ledger (rows keyed by batch; re-runs replace rows for
	the same batches instead of double-counting) — that ledger is what the
	reporting API reads revenue from.
	"""
	qty = int(qty or 0)
	if not batch_type or qty <= 0:
		return {"allocated": 0, "unallocated": max(qty, 0)}

	rows = frappe.db.get_list(
		"Livestock Batch",
		filters={"livestock_type": batch_type, "status": "Ready"},
		fields=["name"],
		order_by="start_date asc",
		ignore_permissions=True,  # R16: hook runs as the submitting user (e.g. Sales User),
		# who has no Livestock Batch read permission; allocation must still see Ready batches.
	)

	allocated = 0
	remaining = qty
	allocated_per_batch = {}
	for row in rows:
		if remaining <= 0:
			break
		batch = frappe.get_doc("Livestock Batch", row["name"])  # read-only: ceiling only
		ceiling = batch.surviving() - int(batch.sold or 0)
		if ceiling <= 0:
			continue
		take = min(remaining, ceiling)
		# R16: elevated counter write — bypasses the doc write-permission gate
		# so a non-admin submitter never blocks; touches only `sold`.
		frappe.db.set_value(
			"Livestock Batch",
			row["name"],
			"sold",
			int(batch.sold or 0) + take,
			update_modified=False,
		)
		allocated += take
		remaining -= take
		allocated_per_batch[row["name"]] = allocated_per_batch.get(row["name"], 0) + take

	if voucher_no and allocated_per_batch:
		_record_batch_sale(batch_type, voucher_type, voucher_no, allocated_per_batch, rate)

	if remaining and getattr(frappe.local, "request", None):
		# NOTE: msgprint takes (msg, indicator=...) — the dict form would
		# crash safe_decode, so the brief's dict literal is spelled out here.
		frappe.msgprint(
			f"{remaining} finished birds of type {batch_type} were allocated to NO batch "
			"(no Ready batch with remaining head).",
			indicator="orange",
		)

	return {"allocated": allocated, "unallocated": remaining}


def _record_batch_sale(batch_type, voucher_doctype, voucher_no, allocated_per_batch, rate=None):
	"""Upsert the invoice's Batch Sale ledger with this allocation's rows.

	Multiple seam calls can contribute to one invoice (one per batch type /
	rate group); rows are keyed by (item_code, batch) — re-allocated batches
	replace their row, others are kept."""
	item_to_type = _finished_item_to_type()
	finished_item = next(
		(item for item, ftype in item_to_type.items() if ftype == batch_type), None
	)
	if not finished_item:
		return

	existing = frappe.db.get_value("Batch Sale", {"voucher_type": voucher_doctype, "voucher_no": voucher_no}, "name")
	if existing:
		sale = frappe.get_doc("Batch Sale", existing)
	else:
		sale = frappe.new_doc("Batch Sale")
		sale.voucher_type = voucher_doctype
		sale.voucher_no = voucher_no
		sale.posting_date = frappe.db.get_value(voucher_doctype, voucher_no, "posting_date")

	for batch_name, qty in allocated_per_batch.items():
		sale.items = [row for row in sale.items if not (row.item_code == finished_item and row.batch == batch_name)]
		sale.append(
			"items",
			{
				"item_code": finished_item,
				"batch": batch_name,
				"qty": qty,
				"amount": flt(qty) * flt(rate or 0),
			},
		)

	sale.save(ignore_permissions=True)  # R16: the submitting user may lack Batch Sale write


def _finished_item_to_type():
	"""Map Livestock Type `finished_item` -> livestock type name."""
	rows = frappe.db.get_all(
		"Livestock Type", filters={"finished_item": ["!=", ""]}, fields=["name", "finished_item"]
	)
	return {row["finished_item"]: row["name"] for row in rows if row.get("finished_item")}


def _allocate_invoice_items(items, voucher_type=None, voucher_no=None):
	"""Sum invoice-item qtys per (batch type, rate) and allocate via the seam.

	Grouping by rate keeps recorded revenue exact when an invoice carries the
	same finished item at two rates."""
	item_to_type = _finished_item_to_type()
	groups = {}
	for item in items or []:
		item_code = item.get("item_code") if isinstance(item, dict) else item.item_code
		qty = item.get("qty") if isinstance(item, dict) else item.qty
		item_rate = (item.get("rate") if isinstance(item, dict) else item.rate) or 0
		batch_type = item_to_type.get(item_code)
		if not batch_type:
			continue
		key = (batch_type, flt(item_rate))
		groups[key] = groups.get(key, 0) + int(qty or 0)

	allocated = 0
	unallocated = 0
	for (batch_type, rate), qty in groups.items():
		result = allocate_sales_to_ready_batches_for_type(
			batch_type=batch_type, qty=qty, voucher_type=voucher_type, voucher_no=voucher_no, rate=rate
		)
		allocated += result["allocated"]
		unallocated += result["unallocated"]
	return {"allocated": allocated, "unallocated": unallocated}


def allocate_sales_to_ready_batches(doc=None, method=None):
	"""Hook entry: Sales Invoice on_submit -> FIFO sale allocation to Ready batches.

	Called positionally as `allocate_sales_to_ready_batches(doc, method)` by the
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
	return _allocate_invoice_items(doc.items, voucher_type=doc.doctype, voucher_no=doc.name)


def revoke_sale_allocation(doc=None, method=None):
	"""Hook entry: Sales Invoice / POS Invoice on_cancel -> undo that voucher's
	allocation.

	Decrements each batch's `sold` by its recorded Batch Sale rows (floored
	at 0 — manual corrections are allowed to have moved the number) and deletes
	the voucher's Batch Sale ledger so cancelled revenue never reports."""
	if doc is None:
		return {"revoked": 0}

	sale_name = frappe.db.get_value(
		"Batch Sale", {"voucher_type": doc.doctype, "voucher_no": doc.name}, "name"
	)
	if not sale_name:
		return {"revoked": 0}

	sale = frappe.get_doc("Batch Sale", sale_name)
	revoked = 0
	for row in sale.items:
		current = int(frappe.db.get_value("Livestock Batch", row.batch, "sold") or 0)
		frappe.db.set_value(
			"Livestock Batch", row.batch, "sold", max(current - int(row.qty or 0), 0), update_modified=False
		)
		revoked += int(row.qty or 0)

	frappe.delete_doc("Batch Sale", sale_name, ignore_permissions=True)
	return {"revoked": revoked}


@frappe.whitelist()
def create_batch_sales_invoice(batch, qty, customer, rate, mode_of_payment="Cash"):
	"""Create + submit a Sales Invoice of `qty` x the batch type's finished item.

	Capped at the batch's `remaining()` — throws
	`f"Only {remaining} head remain on batch {batch}"` when over. The
	on_submit hook allocates the invoice to Ready batches automatically, so
	this helper only reads back the Batch Sale ledger rows the hook wrote:
	returns `{"sales_invoice", "allocated", "unallocated"}` and throws
	`f"Only {allocated} of {qty} allocated — batch ready-state ceilings hit"`
	when any unit fit in NO Ready batch (unallocated is 0 on success).

	Caller needs Sales Invoice create/submit permission (no permission bypass here).

	`mode_of_payment` is accepted for the Task 14 dashboard call signature;
	voucher_type is always "Sales Invoice" (POS is out of scope).
	"""
	batch_doc = frappe.get_doc("Livestock Batch", batch)
	finished_item = frappe.db.get_value("Livestock Type", batch_doc.livestock_type, "finished_item")
	if not finished_item:
		frappe.throw(f"Livestock Type {batch_doc.livestock_type} has no finished item set.")

	qty = int(qty or 0)
	if qty <= 0:
		frappe.throw(frappe._("Qty must be at least 1"))
	remaining = batch_doc.remaining()
	if qty > remaining:
		frappe.throw(f"Only {remaining} head remain on batch {batch}")

	company = frappe.defaults.get_user_default("company")
	if not company:
		frappe.throw(frappe._("Company is not set for this user. Set the company user default."))
	si = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"company": company,
			"customer": customer,
			"posting_date": today(),
			"items": [{"item_code": finished_item, "qty": qty, "rate": flt(rate)}],
		}
	)
	si.insert()
	si.submit()

	sale_name = frappe.db.get_value(
		"Batch Sale", {"voucher_type": "Sales Invoice", "voucher_no": si.name}, "name"
	)
	allocated = 0
	if sale_name:
		sale = frappe.get_doc("Batch Sale", sale_name)
		allocated = sum(int(row.qty or 0) for row in sale.items)
	unallocated = qty - allocated
	if unallocated > 0:
		frappe.throw(f"Only {allocated} of {qty} allocated — batch ready-state ceilings hit")
	return {"sales_invoice": si.name, "allocated": allocated, "unallocated": unallocated}
