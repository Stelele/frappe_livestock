import frappe
from frappe.tests import IntegrationTestCase


class TestHousing(IntegrationTestCase):
	def test_default_status_is_ready(self):
		doc = frappe.get_doc({"doctype": "Housing", "housing_name": "Brooding A", "housing_type": "Brooding"}).insert()
		self.assertEqual(doc.status, "Ready")

	def test_regions_save(self):
		doc = frappe.get_doc({
			"doctype": "Housing",
			"housing_name": "Grower 1",
			"housing_type": "Grower",
			"regions": [{"region_name": "North", "capacity": 200}, {"region_name": "South", "capacity": 200}],
		}).insert()
		self.assertEqual(len(doc.regions), 2)
