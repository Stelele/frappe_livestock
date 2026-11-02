"""Fold legacy Open/Finish Feed Event pairs into one "feed consumed" record.

For every ("batch", "feed_item", "date") group with more than one row:
- if the group has Finish rows, keep the LAST Finish row (deterministic
  walk by creation, name) with qty set to the SUM of the Finish rows' qtys
  and delete the rest;
- if the group has no Finish rows, keep the earliest row with qty set to
  the sum of the group's qtys and delete the rest. Rows with a missing or
  unexpected `event` value are folded into the group sum, never dropped.

NULL dates group together (null-safe `<=>` matching), so legacy NULL-date
rows fold instead of being silently skipped. Single-row groups are no-ops.

Runs pre_model_sync so the legacy `event` column is still present when
upgrading old sites; on the current schema (no `event` column) the same
fold collapses exact duplicate groups by summing qty.
"""

import frappe


def fold_groups(rows: list[dict]) -> list[dict]:
	"""Pure fold decision for one ("batch", "feed_item", "date") group.

	`rows` are mappings with at least ``name``; ``event``/``qty``/``creation``
	are optional (absent on the current schema). The walk is deterministic:
	ordered by (creation, name). Returns a single-element list with::

		[{"keep": <name>, "qty": <folded qty>, "delete": [<names>]}]

	Empty input returns ``[]``; a singleton group keeps its row with its own
	qty and no deletes.
	"""
	ordered = sorted(rows, key=lambda row: (row.get("creation") or "", row.get("name") or ""))
	if not ordered:
		return []
	if len(ordered) == 1:
		only = ordered[0]
		return [{"keep": only.get("name"), "qty": only.get("qty") or 0, "delete": []}]
	finishes = [row for row in ordered if row.get("event") == "Finish"]
	keep = finishes[-1] if finishes else ordered[0]
	pool = finishes if finishes else ordered
	qty = sum((row.get("qty") or 0) for row in pool)
	return [
		{
			"keep": keep.get("name"),
			"qty": qty,
			"delete": [row.get("name") for row in ordered if row.get("name") != keep.get("name")],
		}
	]


def execute():
	if not frappe.db.table_exists("Feed Event"):
		return
	columns = [row[0] for row in frappe.db.sql("desc `tabFeed Event`")]
	event_select = "`event`," if "event" in columns else ""

	groups = frappe.db.sql(
		"""select batch, feed_item, `date`
		from `tabFeed Event`
		group by batch, feed_item, `date`
		having count(*) > 1""",
		as_list=True,
	)
	for batch, feed_item, date in groups:
		rows = frappe.db.sql(
			f"""select name, {event_select} qty, creation from `tabFeed Event`
			where batch <=> %s and feed_item <=> %s and `date` <=> %s
			order by creation asc, name asc""",
			(batch, feed_item, date),
			as_dict=True,
		)
		if len(rows) < 2:
			continue
		decision = fold_groups([dict(row) for row in rows])[0]
		frappe.db.set_value("Feed Event", decision["keep"], "qty", decision["qty"])
		if decision["delete"]:
			frappe.db.delete("Feed Event", {"name": ["in", decision["delete"]]})
