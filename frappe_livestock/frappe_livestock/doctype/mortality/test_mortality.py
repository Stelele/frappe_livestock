import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from frappe_livestock.frappe_livestock.doctype.livestock_type.test_livestock_type import (
	ensure_broiler_type,
)

IGNORE_TEST_RECORD_DEPENDENCIES = ["Item", "Purchase Invoice"]


def _make_batch(placed=5, age=25):
	ensure_broiler_type()
	return frappe.get_doc(
		{
			"doctype": "Livestock Batch",
			"livestock_type": "Broiler",
			"start_date": add_days(today(), -age),
			"quantity_placed": placed,
		}
	).insert()


class TestMortalityHardening(IntegrationTestCase):
	def test_qty_within_placed_inserts_and_cumulative_works(self):
		batch = _make_batch(placed=5)
		frappe.get_doc(
			{
				"doctype": "Mortality",
				"batch": batch.name,
				"date": add_days(today(), -1),
				"qty": 3,
				"reason": "Disease",
			}
		).insert()
		batch = frappe.get_doc("Livestock Batch", batch.name)
		self.assertEqual(batch.mortalities_total(), 3)
		self.assertEqual(batch.surviving(), 2)

	def test_second_mortality_exceeding_placed_raises(self):
		batch = _make_batch(placed=5)
		frappe.get_doc(
			{
				"doctype": "Mortality",
				"batch": batch.name,
				"date": add_days(today(), -1),
				"qty": 3,
				"reason": "Heat",
			}
		).insert()
		with self.assertRaisesRegex(frappe.exceptions.ValidationError, "cannot exceed"):
			frappe.get_doc(
				{
					"doctype": "Mortality",
					"batch": batch.name,
					"date": today(),
					"qty": 3,
					"reason": "Predator",
				}
			).insert()

	def test_age_days_and_stage_stamped_on_insert(self):
		batch = _make_batch(placed=5, age=25)  # 25 days old -> Grower
		doc = frappe.get_doc(
			{
				"doctype": "Mortality",
				"batch": batch.name,
				"date": add_days(today(), -1),
				"qty": 1,
				"reason": "Other",
				"reason_details": "fox got in",
			}
		).insert()
		self.assertEqual(doc.age_days, 25)
		self.assertEqual(doc.stage, "Grower")
