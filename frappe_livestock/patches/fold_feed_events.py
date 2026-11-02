"""Fold legacy Open/Finish Feed Event pairs into one "feed consumed" record.

For every ("batch", "feed_item", "date") group with more than one row:
- if the group has Finish rows, keep the LAST Finish row (its qty is the
  bag's consumed amount) and delete the rest;
- if the group has only Open rows, keep the earliest row with qty set to
  the sum of the group's qtys and delete the rest.

Runs pre_model_sync so the legacy `event` column is still present.
"""

import frappe


def execute():
	if not frappe.db.table_exists("tabFeed Event"):
		return
	columns = [row[0] for row in frappe.db.sql("desc `tabFeed Event`")]
	if "event" not in columns:
		return

	groups = frappe.db.sql(
		"""select batch, feed_item, `date`
		from `tabFeed Event`
		group by batch, feed_item, `date`
		having count(*) > 1""",
		as_list=True,
	)
	for batch, feed_item, date in groups:
		rows = frappe.db.sql(
			"""select name, `event`, qty from `tabFeed Event`
			where batch <=> %s and feed_item <=> %s and `date` <=> %s
			order by creation asc, name asc""",
			(batch, feed_item, date),
			as_dict=True,
		)
		if len(rows) < 2:
			continue
		finishes = [row for row in rows if row.event == "Finish"]
		if finishes:
			keep = finishes[-1].name
			frappe.db.set_value("Feed Event", keep, "qty", finishes[-1].qty or 0)
		else:
			keep = rows[0].name
			frappe.db.set_value(
				"Feed Event", keep, "qty", sum((row.qty or 0) for row in rows)
			)
		frappe.db.delete(
			"Feed Event", {"name": ["in", [row.name for row in rows if row.name != keep]]}
		)
