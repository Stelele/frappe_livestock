"""Daily scheduler nudges for livestock batches.

`daily()` is wired to Frappe's ``daily`` cron tick (see hooks.py). For every
``Active`` batch it emits in-app Notification Log rows to all Livestock
Manager / System Manager users (plus Administrator):

* ready-nudge — expected_ready_date() is today or earlier;
* quiet-nudge — no feed/mortality entry in >= 2 days (or >= 3 days since
  start when the batch has no entries at all).

Each nudge is idempotent per day: a row with the same subject created today
is never duplicated.
"""

import frappe
from frappe.utils import getdate, today


def _recipients() -> list[str]:
	users = frappe.get_all(
		"Has Role",
		filters={
			"role": ["in", ["Livestock Manager", "System Manager"]],
			"parenttype": "User",
		},
		pluck="parent",
	)
	users = sorted({u for u in users if u})
	if "Administrator" not in users:
		users.append("Administrator")
	return users


def _notify(user: str, subject: str, batch_name: str) -> None:
	if frappe.db.exists(
		"Notification Log",
		{"for_user": user, "subject": subject, "creation": [">=", today()]},
	):
		return
	frappe.get_doc(
		{
			"doctype": "Notification Log",
			"for_user": user,
			"from_user": "Administrator",
			"type": "Alert",
			"subject": subject,
			"document_type": "Livestock Batch",
			"document_name": batch_name,
		}
	).insert(ignore_permissions=True)


def _ensure_alert_type() -> None:
	if not frappe.db.exists("Notification Type", "Alert"):
		frappe.get_doc({"doctype": "Notification Type", "type_name": "Alert"}).insert(
			ignore_permissions=True
		)


def daily() -> None:
	_ensure_alert_type()
	users = _recipients()
	td = getdate(today())
	batches = frappe.get_all(
		"Livestock Batch",
		filters={"status": "Active"},
		fields=["name", "start_date"],
	)
	for b in batches:
		batch = frappe.get_doc("Livestock Batch", b.name)

		expected = batch.expected_ready_date()
		if expected and getdate(expected) <= td:
			subject = f"Batch {batch.name} should be marked Ready today"
			for user in users:
				_notify(user, subject, batch.name)

		last_feed = frappe.db.get_value(
			"Feed Event", {"batch": batch.name}, "date", order_by="date desc"
		)
		last_mortality = frappe.db.get_value(
			"Mortality", {"batch": batch.name}, "date", order_by="date desc"
		)
		entry_dates = [getdate(d) for d in (last_feed, last_mortality) if d]
		if entry_dates:
			days = (td - max(entry_dates)).days
		else:
			days = (td - getdate(batch.start_date)).days
		threshold = 3 if not entry_dates else 2
		if days >= threshold:
			subject = f"Batch {batch.name}: no entries recorded in {days} days"
			for user in users:
				_notify(user, subject, batch.name)
