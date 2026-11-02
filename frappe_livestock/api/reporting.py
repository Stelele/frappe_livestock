"""Read-only reporting surface for dashboard consumers (erpnext-dashboard,
holdings app). Design rules:

- Raw rows out; bucketing/grouping/charting is the consumer's job (the owner's
  "compute presentation on the client" rule).
- Read-mostly: nothing here mutates; capture stays in the desk/phone surfaces.
- Every endpoint is gated to System Manager / Livestock Dashboard /
  Livestock Manager.
- Cost ledger = Batch Cost (allocations of purchase invoices); revenue ledger =
  Batch Sale (allocations of sales invoices, written by the on_submit hook).
"""

import frappe

DASHBOARD_ROLES = ("System Manager", "Livestock Dashboard", "Livestock Manager")


def _gate():
	frappe.only_for(DASHBOARD_ROLES)


def _range_filter(from_date=None, to_date=None):
	filters = []
	if from_date:
		filters.append(["posting_date", ">=", from_date])
	if to_date:
		filters.append(["posting_date", "<=", to_date])
	return filters


def _ledger_items(child_doctype, parent_doctype, batch, from_date=None, to_date=None):
	"""Child rows of one batch's ledger docs; the date range filters the PARENT
	doc's posting_date (child tables carry no date of their own)."""
	parents = frappe.get_all(child_doctype, filters={"batch": batch}, pluck="parent", distinct=True)
	if not parents:
		return []
	if from_date or to_date:
		parent_filters = [["name", "in", parents]] + _range_filter(from_date, to_date)
		parents = frappe.get_all(parent_doctype, filters=parent_filters, pluck="name")
	return frappe.get_all(
		child_doctype,
		filters={"parent": ["in", parents]},
		fields=["item_code", "qty", "amount"],
	)


def _batch_rows():
	"""All batches with their computed per-batch aggregates, in one pass each."""
	batches = frappe.get_all(
		"Livestock Batch",
		fields=["name", "livestock_type", "start_date", "quantity_placed", "status", "sold"],
		order_by="start_date asc",
	)

	costs = dict(
		frappe.db.sql(
			"select batch, sum(amount) from `tabBatch Cost Item` group by batch"
		)
	)
	revenues = dict(
		frappe.db.sql(
			"select batch, sum(amount) from `tabBatch Sale Item` group by batch"
		)
	)
	mortalities = dict(
		frappe.db.sql("select batch, sum(qty) from `tabMortality` group by batch")
	)

	type_stages = {}
	type_items = {}
	for row in frappe.get_all(
		"Livestock Type",
		fields=["name", "stocking_item", "finished_item"],
	):
		type_items[row.name] = row
		type_stages[row.name] = frappe.get_all(
			"Livestock Stage",
			filters={"parent": row.name, "parenttype": "Livestock Type"},
			fields=["stage_name", "start_day", "end_day"],
			order_by="start_day asc",
		)

	from frappe_livestock.frappe_livestock.doctype.livestock_type.livestock_type import (
		get_stage_for_age,
	)

	out = []
	for batch in batches:
		age = max((frappe.utils.getdate(frappe.utils.today()) - frappe.utils.getdate(batch.start_date)).days, 0)
		stages = type_stages.get(batch.livestock_type) or []
		stage = get_stage_for_age(stages, age)
		last_day = max((s.end_day for s in stages), default=0)
		total_cost = float(costs.get(batch.name) or 0)
		revenue = float(revenues.get(batch.name) or 0)
		mortalities_total = int(mortalities.get(batch.name) or 0)
		surviving = int(batch.quantity_placed or 0) - mortalities_total
		remaining = surviving - int(batch.sold or 0)
		profit = revenue - total_cost
		margin = (profit / revenue) if revenue else 0
		out.append(
			{
				"name": batch.name,
				"livestock_type": batch.livestock_type,
				"start_date": batch.start_date,
				"status": batch.status,
				"age_days": age,
				"stage": stage["stage_name"] if stage else None,
				"expected_ready_date": frappe.utils.add_days(batch.start_date, last_day) if last_day else None,
				"quantity_placed": int(batch.quantity_placed or 0),
				"mortalities_total": mortalities_total,
				"surviving": surviving,
				"remaining": remaining,
				"sold": int(batch.sold or 0),
				"total_cost": total_cost,
				"cost_per_head": (total_cost / surviving) if surviving else 0.0,
				"revenue": revenue,
				"profit": profit,
				"margin": margin,
			}
		)
	return out


@frappe.whitelist()
def portfolio(company=None, status=None, from_date=None, to_date=None):
	"""One row per batch with computed metrics. `company` is accepted for
	interface stability but not yet filtered on (Livestock Batch carries no company in
	phase 1 — the farm operates one company)."""
	_gate()
	rows = _batch_rows()
	if status:
		rows = [row for row in rows if row["status"] == status]
	if from_date:
		rows = [row for row in rows if row["start_date"] and str(row["start_date"]) >= str(from_date)]
	if to_date:
		rows = [row for row in rows if row["start_date"] and str(row["start_date"]) <= str(to_date)]
	return rows


@frappe.whitelist()
def batch_pl(batch, from_date=None, to_date=None):
	"""Per-batch profit & loss: cost lines by category, revenue lines, totals."""
	_gate()
	livestock_type = frappe.db.get_value("Livestock Batch", batch, "livestock_type")
	stocking_item = frappe.db.get_value("Livestock Type", livestock_type, "stocking_item")

	cost_rows = _ledger_items("Batch Cost Item", "Batch Cost", batch, from_date, to_date)

	item_groups = {}
	if cost_rows:
		groups = frappe.get_all(
			"Item",
			filters={"name": ["in", list({row.item_code for row in cost_rows})]},
			fields=["name", "item_group"],
		)
		item_groups = {row.name: row.item_group for row in groups}

	costs = []
	for row in cost_rows:
		category = "stocking" if row.item_code == stocking_item else (item_groups.get(row.item_code) or row.item_code)
		costs.append({"category": category, "item_code": row.item_code, "qty": row.qty, "amount": row.amount})

	sale_rows = _ledger_items("Batch Sale Item", "Batch Sale", batch, from_date, to_date)
	revenue = [
		{"item_code": row.item_code, "qty": row.qty, "amount": row.amount} for row in sale_rows
	]

	total_cost = sum(row["amount"] or 0 for row in costs)
	total_revenue = sum(row["amount"] or 0 for row in revenue)
	profit = total_revenue - total_cost
	return {
		"costs": costs,
		"revenue": revenue,
		"totals": {
			"total_cost": total_cost,
			"total_revenue": total_revenue,
			"profit": profit,
			"margin": (profit / total_revenue) if total_revenue else 0,
		},
	}


def _batch_vouchers(batch):
	"""The accounting vouchers backing a batch: cost allocations (PI + their
	receipts + payments) and sale allocations (Sales Invoices)."""
	cost_invoices = [
		row[0]
		for row in frappe.db.sql(
			"""select distinct fc.purchase_invoice
			from `tabBatch Cost` fc join `tabBatch Cost Item` fci on fci.parent = fc.name
			where fci.batch = %s""",
			batch,
		)
	]
	sale_vouchers = frappe.db.sql(
		"""select distinct fs.voucher_type, fs.voucher_no
		from `tabBatch Sale` fs join `tabBatch Sale Item` fsi on fsi.parent = fs.name
		where fsi.batch = %s""",
		batch,
	)

	receipts = []
	payments = []
	for invoice in cost_invoices:
		receipts += [
			row[0]
			for row in frappe.db.sql(
				"select distinct purchase_receipt from `tabPurchase Invoice Item` where parent = %s and purchase_receipt is not null",
				invoice,
			)
		]
		payments += [
			row[0]
			for row in frappe.db.sql(
				"select parent from `tabPayment Entry Reference` where reference_doctype = 'Purchase Invoice' and reference_name = %s",
				invoice,
			)
		]

	vouchers = {
		"Purchase Invoice": cost_invoices,
		"Purchase Receipt": receipts,
		"Payment Entry": payments,
	}
	for voucher_type, voucher_no in sale_vouchers:
		vouchers.setdefault(voucher_type, []).append(voucher_no)

	return vouchers


@frappe.whitelist()
def batch_gl_entries(batch, from_date=None, to_date=None):
	"""The journal entries backing a batch: GL Entries of every voucher its
	cost/sale allocations point at. Raw rows; read-only join, no new writes."""
	_gate()
	vouchers = _batch_vouchers(batch)

	conditions = []
	values = []
	for voucher_type, names in vouchers.items():
		if names:
			conditions.append("(voucher_type = %s and voucher_no in %s)")
			values += [voucher_type, tuple(names)]

	if not conditions:
		return []

	# parenthesise: the or-groups must not swallow the and-ed date filters
	query = (
		"select posting_date, account, debit, credit, voucher_type, voucher_no, remarks "
		"from `tabGL Entry` where (" + " or ".join(conditions) + ")"
	)
	if from_date:
		query += " and posting_date >= %s"
		values.append(from_date)
	if to_date:
		query += " and posting_date <= %s"
		values.append(to_date)
	query += " order by posting_date asc, voucher_no asc"

	return frappe.db.sql(query, values, as_dict=True)


@frappe.whitelist()
def feed_timeline(batch=None, from_date=None, to_date=None):
	"""Raw feed consumption rows for one batch (or all), in date order."""
	_gate()
	filters = []
	if batch:
		filters.append(["batch", "=", batch])
	if from_date:
		filters.append(["date", ">=", from_date])
	if to_date:
		filters.append(["date", "<=", to_date])
	return frappe.db.get_list(
		"Feed Event",
		filters=filters,
		fields=["name", "batch", "feed_item", "date", "qty"],
		order_by="date asc",
	)


@frappe.whitelist()
def mortality_rows(batch=None, from_date=None, to_date=None):
	"""Raw mortality rows for one batch (or all), in date order."""
	_gate()
	filters = []
	if batch:
		filters.append(["batch", "=", batch])
	if from_date:
		filters.append(["date", ">=", from_date])
	if to_date:
		filters.append(["date", "<=", to_date])
	return frappe.db.get_list(
		"Mortality",
		filters=filters,
		fields=["name", "batch", "date", "qty", "reason"],
		order_by="date asc",
	)


@frappe.whitelist()
def get_ops_snapshot(batch):
	"""One-call ops snapshot for a batch: summary + feed + weights + freshness + P&L + readiness.

	Opens with the same 14 keys as `api.batch.get_batch_summary` (same doc-method
	math), then the dashboard's derived numbers — all read-only. FCR is honest:
	it needs a positive weight GAIN (latest minus earliest average weight); a
	single weighing or flat weights yield `fcr = None`, never a made-up ratio.
	"""
	_gate()
	doc = frappe.get_doc("Livestock Batch", batch)
	today = frappe.utils.getdate(frappe.utils.today())

	mortalities_total = doc.mortalities_total()
	quantity_placed = int(doc.quantity_placed or 0)

	feed_rows = frappe.db.get_list(
		"Feed Event", filters={"batch": batch}, fields=["date", "qty"], order_by="date asc"
	)
	feed_consumed_total = sum(float(row.qty or 0) for row in feed_rows)
	feed_consumed_today = sum(float(row.qty or 0) for row in feed_rows if str(row.date) == str(today))
	last_feed_date = str(feed_rows[-1].date) if feed_rows else None

	stocking_item = frappe.db.get_value("Livestock Type", doc.livestock_type, "stocking_item")
	cost_rows = frappe.db.get_all("Batch Cost Item", filters={"batch": batch}, fields=["item_code", "amount"])
	feed_bought_total = sum(float(row.amount or 0) for row in cost_rows if row.item_code != stocking_item)

	mort_dates = frappe.db.get_list(
		"Mortality", filters={"batch": batch}, fields=["date"], order_by="date asc"
	)
	last_mortality_date = str(mort_dates[-1].date) if mort_dates else None

	weight_rows = frappe.db.get_list(
		"Livestock Weight",
		filters={"batch": batch},
		fields=["date", "average_weight_kg"],
		order_by="date asc",
	)
	if weight_rows:
		first, last = weight_rows[0], weight_rows[-1]
		earliest_weight = {"date": str(first.date), "average_weight_kg": first.average_weight_kg}
		latest_weight = {"date": str(last.date), "average_weight_kg": last.average_weight_kg}
		weight_gain_kg = float(last.average_weight_kg or 0) - float(first.average_weight_kg or 0)
	else:
		earliest_weight = None
		latest_weight = None
		weight_gain_kg = 0.0
	fcr = (feed_consumed_total / weight_gain_kg) if weight_gain_kg > 0 else None

	revenue = float(
		frappe.db.sql("select sum(amount) from `tabBatch Sale Item` where batch = %s", batch)[0][0]
		or 0
	)
	total_cost = doc.total_cost()
	profit = revenue - total_cost
	margin = (profit / revenue) if revenue else 0

	expected_ready = doc.expected_ready_date()
	days_to_ready = (frappe.utils.getdate(expected_ready) - today).days if expected_ready else None

	return {
		"name": doc.name,
		"livestock_type": doc.livestock_type,
		"start_date": doc.start_date,
		"age_days": doc.age_days(),
		"stage": doc.stage_name(),
		"expected_ready_date": expected_ready,
		"quantity_placed": quantity_placed,
		"mortalities_total": mortalities_total,
		"surviving": doc.surviving(),
		"remaining": doc.remaining(),
		"sold": int(doc.sold or 0),
		"total_cost": total_cost,
		"cost_per_head": doc.cost_per_head(),
		"status": doc.status,
		"mortality_pct": (mortalities_total / quantity_placed) if quantity_placed else 0.0,
		"feed_consumed_today": feed_consumed_today,
		"feed_consumed_total": feed_consumed_total,
		"feed_bought_total": feed_bought_total,
		"earliest_weight": earliest_weight,
		"latest_weight": latest_weight,
		"earliest_weight_kg": earliest_weight["average_weight_kg"] if earliest_weight else None,
		"earliest_weight_date": earliest_weight["date"] if earliest_weight else None,
		"latest_weight_kg": latest_weight["average_weight_kg"] if latest_weight else None,
		"latest_weight_date": latest_weight["date"] if latest_weight else None,
		"last_weight_kg": latest_weight["average_weight_kg"] if latest_weight else None,
		"last_weight_date": latest_weight["date"] if latest_weight else None,
		"weight_gain_kg": weight_gain_kg,
		"fcr": fcr,
		"last_feed_date": last_feed_date,
		"last_mortality_date": last_mortality_date,
		"revenue": revenue,
		"profit": profit,
		"margin": margin,
		"days_to_ready": days_to_ready,
	}
