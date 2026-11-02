import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, today

from frappe_livestock.frappe_livestock.doctype.livestock_type.test_livestock_type import (
	ensure_broiler_type,
)

IGNORE_TEST_RECORD_DEPENDENCIES = ["Item", "Purchase Invoice"]


def _make_batch(placed=500):
	ensure_broiler_type()
	return frappe.get_doc(
		{
			"doctype": "Livestock Batch",
			"livestock_type": "Broiler",
			"start_date": today(),
			"quantity_placed": placed,
		}
	).insert()


def _make_weight(batch_name, avg, date=None, sample_size=20):
	return frappe.get_doc(
		{
			"doctype": "Livestock Weight",
			"batch": batch_name,
			"date": date or today(),
			"average_weight_kg": avg,
			"sample_size": sample_size,
		}
	).insert()


class TestLivestockWeight(IntegrationTestCase):
	def test_valid_weight_inserts(self):
		batch = _make_batch()
		doc = _make_weight(batch.name, 1.6, sample_size=20)
		self.assertTrue(doc.name)
		self.assertEqual(float(doc.average_weight_kg), 1.6)
		self.assertEqual(int(doc.sample_size), 20)

	def test_zero_average_weight_throws(self):
		batch = _make_batch()
		with self.assertRaises(frappe.exceptions.ValidationError):
			_make_weight(batch.name, 0)

	def test_negative_sample_size_throws(self):
		batch = _make_batch()
		with self.assertRaises(frappe.exceptions.ValidationError):
			_make_weight(batch.name, 1.6, sample_size=-1)

	def test_latest_weight_is_none_when_no_rows(self):
		batch = _make_batch()
		self.assertIsNone(frappe.get_doc("Livestock Batch", batch.name).latest_weight())

	def test_latest_weight_returns_newest_by_date(self):
		batch = _make_batch()
		_make_weight(batch.name, 1.2, date=add_days(today(), -2))
		_make_weight(batch.name, 1.6, date=today())
		latest = frappe.get_doc("Livestock Batch", batch.name).latest_weight()
		self.assertEqual(getdate(latest["date"]), getdate(today()))
		self.assertEqual(float(latest["average_weight_kg"]), 1.6)

	def test_latest_weight_newest_wins_regardless_of_insert_order(self):
		batch = _make_batch()
		_make_weight(batch.name, 2.0, date=today())
		_make_weight(batch.name, 0.8, date=add_days(today(), -5))
		latest = frappe.get_doc("Livestock Batch", batch.name).latest_weight()
		self.assertEqual(getdate(latest["date"]), getdate(today()))
		self.assertEqual(float(latest["average_weight_kg"]), 2.0)


class TestHousingMovementComment(IntegrationTestCase):
	def _make_housing(self, name):
		if frappe.db.exists("Housing", name):
			return frappe.get_doc("Housing", name)
		return frappe.get_doc(
			{"doctype": "Housing", "housing_name": name, "housing_type": "General"}
		).insert()

	def _move_comments(self, batch_name):
		return frappe.get_all(
			"Comment",
			filters={
				"comment_type": "Comment",
				"reference_doctype": "Livestock Batch",
				"reference_name": batch_name,
			},
			fields=["content"],
			order_by="creation asc",
		)

	def test_first_housing_assignment_logs_from_no_housing(self):
		h1 = self._make_housing("Move House A")
		batch = _make_batch()
		batch.housing = h1.name
		batch.save()
		moves = [c for c in self._move_comments(batch.name) if (c.content or "").startswith("Moved from")]
		self.assertEqual(len(moves), 1)
		self.assertIn("no housing", moves[0].content)
		self.assertIn(h1.name, moves[0].content)

	def test_housing_change_inserts_one_comment(self):
		h1 = self._make_housing("Move House A")
		h2 = self._make_housing("Move House B")
		batch = _make_batch()
		batch.housing = h1.name
		batch.save()
		before = len(self._move_comments(batch.name))
		batch.housing = h2.name
		batch.save()
		comments = self._move_comments(batch.name)
		moves = [c for c in comments if (c.content or "").startswith("Moved from")]
		self.assertEqual(len(moves), before + 1)
		self.assertIn(h1.name, moves[-1].content)
		self.assertIn(h2.name, moves[-1].content)

	def test_unchanged_housing_inserts_no_comment(self):
		h1 = self._make_housing("Still House A")
		batch = _make_batch()
		batch.housing = h1.name
		batch.save()
		before = len(self._move_comments(batch.name))
		batch = frappe.get_doc("Livestock Batch", batch.name)
		batch.save()
		after = len(self._move_comments(batch.name))
		self.assertEqual(before, after)
