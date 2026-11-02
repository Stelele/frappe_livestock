import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from frappe_livestock.frappe_livestock.doctype.feed_event.test_feed_event import (
	FEED_ITEM_CODE,
	ensure_feed_item,
)
from frappe_livestock.tasks import daily

TYPE_NAME = "T16 Broiler"
STAGES = [
	{"stage_name": "Day Old Chick", "start_day": 0, "end_day": 20},
	{"stage_name": "Grower", "start_day": 21, "end_day": 41},
	{"stage_name": "Broiler", "start_day": 42, "end_day": 48},
]


def ensure_task_type():
	if not frappe.db.exists("Livestock Type", TYPE_NAME):
		frappe.get_doc(
			{
				"doctype": "Livestock Type",
				"livestock_type_name": TYPE_NAME,
				"stages": STAGES,
			}
		).insert(ignore_if_duplicate=True)


class TestDailyNudges(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		ensure_task_type()
		ensure_feed_item()
		self.old_start = add_days(today(), -60)
		self.stale_start = add_days(today(), -10)
		self.old_name = f"{TYPE_NAME} {self.old_start}"
		self.stale_name = f"{TYPE_NAME} {self.stale_start}"
		self.fresh_name = f"{TYPE_NAME} {today()}"
		for name in (self.old_name, self.stale_name, self.fresh_name):
			frappe.db.delete("Notification Log", {"subject": ["like", f"%{name}%"]})
			frappe.db.delete("Feed Event", {"batch": name})
			frappe.db.delete("Mortality", {"batch": name})
			frappe.db.delete("Livestock Batch", {"name": name})
		frappe.db.commit()

	def _make_batch(self, start, qty=100):
		return frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": TYPE_NAME,
				"start_date": start,
				"quantity_placed": qty,
				"status": "Active",
			}
		).insert()

	def _count(self, subject):
		return frappe.db.count("Notification Log", {"subject": subject})

	def test_ready_and_quiet_nudges_then_idempotent(self):
		self._make_batch(self.old_start)
		ready_subject = f"Batch {self.old_name} should be marked Ready today"
		quiet_subject = f"Batch {self.old_name}: no entries recorded in 60 days"

		daily()

		self.assertGreaterEqual(self._count(ready_subject), 1)
		self.assertGreaterEqual(self._count(quiet_subject), 1)

		# second run same day: no duplicates
		ready_before = self._count(ready_subject)
		quiet_before = self._count(quiet_subject)
		daily()
		self.assertEqual(self._count(ready_subject), ready_before)
		self.assertEqual(self._count(quiet_subject), quiet_before)

	def test_stale_entries_batch_gets_quiet_nudge(self):
		batch = self._make_batch(self.stale_start)
		frappe.get_doc(
			{
				"doctype": "Feed Event",
				"batch": batch.name,
				"feed_item": FEED_ITEM_CODE,
				"date": add_days(today(), -3),
				"qty": 2,
			}
		).insert()
		quiet_subject = f"Batch {self.stale_name}: no entries recorded in 3 days"

		daily()

		self.assertGreaterEqual(self._count(quiet_subject), 1)
		quiet_before = self._count(quiet_subject)
		daily()
		self.assertEqual(self._count(quiet_subject), quiet_before)

	def test_fresh_batch_gets_no_nudge(self):
		batch = self._make_batch(today())
		frappe.get_doc(
			{
				"doctype": "Feed Event",
				"batch": batch.name,
				"feed_item": FEED_ITEM_CODE,
				"date": today(),
				"qty": 1,
			}
		).insert()

		daily()

		self.assertEqual(
			frappe.db.count("Notification Log", {"subject": ["like", f"%{self.fresh_name}%"]}),
			0,
		)
