"""Read-only reporting surface for dashboard consumers (erpnext-dashboard,
holdings app). Design rules:

- Raw rows out; bucketing/grouping/charting is the consumer's job (the owner's
  "compute presentation on the client" rule).
- Read-mostly: nothing here mutates; capture stays in the desk/phone surfaces.
- Every endpoint is gated to System Manager / Livestock Dashboard.
- Cost ledger = Flock Cost (allocations of purchase invoices); revenue ledger =
  Flock Sale (allocations of sales invoices, written by the on_submit hook).
"""

import frappe

DASHBOARD_ROLES = ("System Manager", "Livestock Dashboard")


def _gate():
	frappe.only_for(DASHBOARD_ROLES)


def _range_filter(from_date=None, to_date=None):
	filters = []
	if from_date:
		filters.append(["posting_date", ">=", from_date])
	if to_date:
		filters.append(["posting_date", "<=", to_date])
	return filters


def _ledger_items(child_doctype, parent_doctype, flock, from_date=None, to_date=None):
	"""Child rows of one flock's ledger docs; the date range filters the PARENT
	doc's posting_date (child tables carry no date of their own)."""
	parents = frappe.get_all(child_doctype, filters={"flock": flock}, pluck="parent", distinct=True)
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


def _flock_rows():
	"""All flocks with their computed per-flock aggregates, in one pass each."""
	flocks = frappe.get_all(
		"Flock",
		fields=["name", "livestock_type", "start_date", "quantity_placed", "status", "birds_sold"],
		order_by="start_date asc",
	)

	costs = dict(
		frappe.db.sql(
			"select flock, sum(amount) from `tabFlock Cost Item` group by flock"
		)
	)
	revenues = dict(
		frappe.db.sql(
			"select flock, sum(amount) from `tabFlock Sale Item` group by flock"
		)
	)
	mortalities = dict(
		frappe.db.sql("select flock, sum(qty) from `tabMortality` group by flock")
	)

	type_stages = {}
	type_items = {}
	for row in frappe.get_all(
		"Livestock Type",
		fields=["name", "chick_item", "finished_item"],
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
	for flock in flocks:
		age = max((frappe.utils.getdate(frappe.utils.today()) - frappe.utils.getdate(flock.start_date)).days, 0)
		stages = type_stages.get(flock.livestock_type) or []
		stage = get_stage_for_age(stages, age)
		last_day = max((s.end_day for s in stages), default=0)
		total_cost = float(costs.get(flock.name) or 0)
		revenue = float(revenues.get(flock.name) or 0)
		mortalities_total = int(mortalities.get(flock.name) or 0)
		surviving = int(flock.quantity_placed or 0) - mortalities_total
		remaining = surviving - int(flock.birds_sold or 0)
		profit = revenue - total_cost
		margin = (profit / revenue) if revenue else 0
		out.append(
			{
				"name": flock.name,
				"livestock_type": flock.livestock_type,
				"start_date": flock.start_date,
				"status": flock.status,
				"age_days": age,
				"stage": stage["stage_name"] if stage else None,
				"expected_ready_date": frappe.utils.add_days(flock.start_date, last_day) if last_day else None,
				"quantity_placed": int(flock.quantity_placed or 0),
				"mortalities_total": mortalities_total,
				"surviving_birds": surviving,
				"remaining_birds": remaining,
				"birds_sold": int(flock.birds_sold or 0),
				"total_cost": total_cost,
				"cost_per_bird": (total_cost / surviving) if surviving else 0.0,
				"revenue": revenue,
				"profit": profit,
				"margin": margin,
			}
		)
	return out


@frappe.whitelist()
def portfolio(company=None, status=None, from_date=None, to_date=None):
	"""One row per flock with computed metrics. `company` is accepted for
	interface stability but not yet filtered on (Flock carries no company in
	phase 1 — the farm operates one company)."""
	_gate()
	rows = _flock_rows()
	if status:
		rows = [row for row in rows if row["status"] == status]
	if from_date:
		rows = [row for row in rows if row["start_date"] and str(row["start_date"]) >= str(from_date)]
	if to_date:
		rows = [row for row in rows if row["start_date"] and str(row["start_date"]) <= str(to_date)]
	return rows


@frappe.whitelist()
def flock_pl(flock, from_date=None, to_date=None):
	"""Per-flock profit & loss: cost lines by category, revenue lines, totals."""
	_gate()
	livestock_type = frappe.db.get_value("Flock", flock, "livestock_type")
	chick_item = frappe.db.get_value("Livestock Type", livestock_type, "chick_item")

	cost_rows = _ledger_items("Flock Cost Item", "Flock Cost", flock, from_date, to_date)

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
		category = "chicks" if row.item_code == chick_item else (item_groups.get(row.item_code) or row.item_code)
		costs.append({"category": category, "item_code": row.item_code, "qty": row.qty, "amount": row.amount})

	sale_rows = _ledger_items("Flock Sale Item", "Flock Sale", flock, from_date, to_date)
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


def _flock_vouchers(flock):
	"""The accounting vouchers backing a flock: cost allocations (PI + their
	receipts + payments) and sale allocations (Sales Invoices)."""
	cost_invoices = [
		row[0]
		for row in frappe.db.sql(
			"""select distinct fc.purchase_invoice
			from `tabFlock Cost` fc join `tabFlock Cost Item` fci on fci.parent = fc.name
			where fci.flock = %s""",
			flock,
		)
	]
	sale_invoices = [
		row[0]
		for row in frappe.db.sql(
			"""select distinct fs.sales_invoice
			from `tabFlock Sale` fs join `tabFlock Sale Item` fsi on fsi.parent = fs.name
			where fsi.flock = %s""",
			flock,
		)
	]

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

	return {
		"Purchase Invoice": cost_invoices,
		"Purchase Receipt": receipts,
		"Payment Entry": payments,
		"Sales Invoice": sale_invoices,
	}


@frappe.whitelist()
def flock_gl_entries(flock, from_date=None, to_date=None):
	"""The journal entries backing a flock: GL Entries of every voucher its
	cost/sale allocations point at. Raw rows; read-only join, no new writes."""
	_gate()
	vouchers = _flock_vouchers(flock)

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
def feed_timeline(flock=None, from_date=None, to_date=None):
	"""Raw feed rows: bag events for one flock (or all), in date order."""
	_gate()
	filters = [["event", "in", ["Open", "Finish"]]]
	if flock:
		filters.append(["flock", "=", flock])
	if from_date:
		filters.append(["date", ">=", from_date])
	if to_date:
		filters.append(["date", "<=", to_date])
	return frappe.db.get_list(
		"Feed Event",
		filters=filters,
		fields=["name", "flock", "feed_item", "event", "date", "qty"],
		order_by="date asc",
	)


@frappe.whitelist()
def mortality_rows(flock=None, from_date=None, to_date=None):
	"""Raw mortality rows for one flock (or all), in date order."""
	_gate()
	filters = []
	if flock:
		filters.append(["flock", "=", flock])
	if from_date:
		filters.append(["date", ">=", from_date])
	if to_date:
		filters.append(["date", "<=", to_date])
	return frappe.db.get_list(
		"Mortality",
		filters=filters,
		fields=["name", "flock", "date", "qty", "reason"],
		order_by="date asc",
	)
