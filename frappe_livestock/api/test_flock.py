import frappe
from frappe.tests import IntegrationTestCase

from frappe_livestock.api.flock import get_flock_summary


class TestFlockSummary(IntegrationTestCase):
	def test_summary_includes_all_computed_fields(self):
		flock = frappe.get_doc(
			{
				"doctype": "Flock",
				"livestock_type": "Broiler",
				"start_date": frappe.utils.today(),
				"quantity_placed": 500,
			}
		).insert()
		s = get_flock_summary(flock.name)
		for key in [
			"age_days",
			"stage",
			"expected_ready_date",
			"surviving_birds",
			"remaining_birds",
			"total_cost",
			"cost_per_bird",
			"status",
		]:
			self.assertIn(key, s)
		self.assertEqual(s["surviving_birds"], 500)
