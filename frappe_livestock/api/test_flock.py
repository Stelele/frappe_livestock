import frappe
from frappe.tests import IntegrationTestCase

from frappe_livestock.api.flock import get_flock_summary


class TestFlockSummary(IntegrationTestCase):
	def setUp(self):
		self.flock_name = f"Broiler {frappe.utils.today()}"
		# guard against rows leaked by pre-fix committed runs
		frappe.db.delete("Flock Cost Item", {"flock": self.flock_name})
		frappe.db.delete("Mortality", {"flock": self.flock_name})
		frappe.db.delete("Flock", {"name": self.flock_name})
		frappe.db.delete("Flock Cost Item", {"flock": "Broiler 2026-10-10"})
		frappe.db.delete("Mortality", {"flock": "Broiler 2026-10-10"})
		frappe.db.delete("Flock", {"name": "Broiler 2026-10-10"})
		frappe.get_doc(
			{
				"doctype": "Flock",
				"livestock_type": "Broiler",
				"start_date": frappe.utils.today(),
				"quantity_placed": 500,
			}
		).insert()

	def test_summary_includes_all_computed_fields(self):
		s = get_flock_summary(self.flock_name)
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
