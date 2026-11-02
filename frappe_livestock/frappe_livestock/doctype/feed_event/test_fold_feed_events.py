import unittest

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from frappe_livestock.frappe_livestock.doctype.livestock_type.test_livestock_type import (
	ensure_broiler_type,
)
from frappe_livestock.frappe_livestock.doctype.feed_event.test_feed_event import (
	FEED_ITEM_CODE,
	ensure_feed_item,
)
from frappe_livestock.patches.fold_feed_events import execute, fold_groups


class FoldGroupsUnitTest(unittest.TestCase):
	"""Pure fold-decision tests with synthetic row lists (no DB)."""

	def test_open_plus_finish_keeps_finish_qty(self):
		decision = fold_groups(
			[
				{"name": "open-1", "event": "Open", "qty": 10, "creation": "2026-01-01 10:00:00"},
				{"name": "fin-1", "event": "Finish", "qty": 3.5, "creation": "2026-01-01 11:00:00"},
			]
		)[0]
		self.assertEqual(decision["keep"], "fin-1")
		self.assertEqual(decision["qty"], 3.5)
		self.assertEqual(decision["delete"], ["open-1"])

	def test_open_only_pair_sums_opens(self):
		decision = fold_groups(
			[
				{"name": "open-1", "event": "Open", "qty": 2, "creation": "2026-01-01 10:00:00"},
				{"name": "open-2", "event": "Open", "qty": 3, "creation": "2026-01-01 11:00:00"},
			]
		)[0]
		self.assertEqual(decision["keep"], "open-1")
		self.assertEqual(decision["qty"], 5)
		self.assertEqual(decision["delete"], ["open-2"])

	def test_two_opens_no_finish_sum(self):
		"""Two Open rows and no Finish collapse to one row with the summed qty."""
		decision = fold_groups(
			[
				{"name": "b", "event": "Open", "qty": 1.5, "creation": "2026-01-02 10:00:00"},
				{"name": "a", "event": "Open", "qty": 2.5, "creation": "2026-01-01 10:00:00"},
			]
		)[0]
		self.assertEqual(decision["keep"], "a")
		self.assertEqual(decision["qty"], 4.0)
		self.assertEqual(decision["delete"], ["b"])

	def test_multiple_finishes_sum_finish_qtys(self):
		"""Controller ruling: Finish-present group folds to the SUM of Finish qtys."""
		decision = fold_groups(
			[
				{"name": "open-1", "event": "Open", "qty": 10, "creation": "2026-01-01 09:00:00"},
				{"name": "fin-1", "event": "Finish", "qty": 2, "creation": "2026-01-01 10:00:00"},
				{"name": "fin-2", "event": "Finish", "qty": 4, "creation": "2026-01-01 11:00:00"},
			]
		)[0]
		self.assertEqual(decision["keep"], "fin-2")
		self.assertEqual(decision["qty"], 6)
		self.assertEqual(decision["delete"], ["open-1", "fin-1"])

	def test_unknown_event_rows_fold_into_sum_not_dropped(self):
		decision = fold_groups(
			[
				{"name": "open-1", "event": "Open", "qty": 2, "creation": "2026-01-01 10:00:00"},
				{"name": "odd-1", "event": "SomethingElse", "qty": 3, "creation": "2026-01-01 11:00:00"},
			]
		)[0]
		self.assertEqual(decision["qty"], 5)
		self.assertEqual(len(decision["delete"]), 1)

	def test_current_schema_rows_without_event_sum(self):
		"""Rows shaped like the current schema (no `event` key) collapse by sum."""
		decision = fold_groups(
			[
				{"name": "r1", "qty": 1.5, "creation": "2026-01-01 10:00:00"},
				{"name": "r2", "qty": 2.5, "creation": "2026-01-01 11:00:00"},
			]
		)[0]
		self.assertEqual(decision["keep"], "r1")
		self.assertEqual(decision["qty"], 4.0)
		self.assertEqual(decision["delete"], ["r2"])

	def test_singleton_is_noop(self):
		decision = fold_groups([{"name": "only", "event": "Finish", "qty": 7}])[0]
		self.assertEqual(decision, {"keep": "only", "qty": 7, "delete": []})


class TestFoldFeedEventsPatch(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		ensure_broiler_type()
		ensure_feed_item()
		if frappe.db.exists("Livestock Batch", f"Broiler {today()}"):
			frappe.delete_doc("Livestock Batch", f"Broiler {today()}", force=True)

	def _make_batch(self):
		return frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": today(),
				"quantity_placed": 500,
			}
		).insert()

	def test_execute_collapses_current_schema_duplicates(self):
		"""Same-(batch, item, date) rows on the current schema fold to one summed row."""
		batch = self._make_batch()
		for qty in (1.5, 2.5, 1.0):
			frappe.get_doc(
				{
					"doctype": "Feed Event",
					"batch": batch.name,
					"feed_item": FEED_ITEM_CODE,
					"date": today(),
					"qty": qty,
				}
			).insert()
		singleton = frappe.get_doc(
			{
				"doctype": "Feed Event",
				"batch": batch.name,
				"feed_item": FEED_ITEM_CODE,
				"date": frappe.utils.add_days(today(), -1),
				"qty": 9,
			}
		).insert()

		execute()

		remaining = frappe.get_all(
			"Feed Event",
			filters={"batch": batch.name, "feed_item": FEED_ITEM_CODE, "date": today()},
			fields=["name", "qty"],
		)
		self.assertEqual(len(remaining), 1)
		self.assertAlmostEqual(remaining[0].qty, 5.0)
		self.assertTrue(frappe.db.exists("Feed Event", singleton.name))
		self.assertEqual(frappe.db.get_value("Feed Event", singleton.name, "qty"), 9)
