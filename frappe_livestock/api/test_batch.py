import frappe
from frappe.tests import IntegrationTestCase

from frappe_livestock.api.batch import get_batch_summary


class TestBatchSummary(IntegrationTestCase):
	def setUp(self):
		self.batch_name = f"Broiler {frappe.utils.today()}"
		# guard against rows leaked by pre-fix committed runs
		frappe.db.delete("Batch Cost Item", {"batch": self.batch_name})
		frappe.db.delete("Mortality", {"batch": self.batch_name})
		frappe.db.delete("Livestock Batch", {"name": self.batch_name})
		frappe.db.delete("Batch Cost Item", {"batch": "Broiler 2026-10-10"})
		frappe.db.delete("Mortality", {"batch": "Broiler 2026-10-10"})
		frappe.db.delete("Livestock Batch", {"name": "Broiler 2026-10-10"})
		frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": frappe.utils.today(),
				"quantity_placed": 500,
			}
		).insert()

	def test_summary_includes_all_computed_fields(self):
		s = get_batch_summary(self.batch_name)
		for key in [
			"age_days",
			"stage",
			"expected_ready_date",
			"surviving",
			"remaining",
			"total_cost",
			"cost_per_head",
			"status",
		]:
			self.assertIn(key, s)
		self.assertEqual(s["surviving"], 500)
