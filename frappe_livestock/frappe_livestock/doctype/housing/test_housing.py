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

	def test_mark_occupied_sets_status_and_last_used_date(self):
		doc = frappe.get_doc({"doctype": "Housing", "housing_name": "Occ Test", "housing_type": "General"}).insert()
		doc.mark_occupied()
		self.assertEqual(doc.status, "Occupied")
		self.assertEqual(str(doc.last_used_date), str(frappe.utils.today()))

	def test_mark_released_sets_ready(self):
		doc = frappe.get_doc({"doctype": "Housing", "housing_name": "Rel Test", "housing_type": "General"}).insert()
		doc.mark_occupied()
		doc.mark_released()
		self.assertEqual(doc.status, "Ready")

	def test_mark_released_cleaned_stamps_date(self):
		doc = frappe.get_doc({"doctype": "Housing", "housing_name": "Clean Test", "housing_type": "General"}).insert()
		doc.mark_released(cleaned=True)
		self.assertEqual(str(doc.last_cleaned_date), str(frappe.utils.today()))

	def test_mark_released_not_cleaned_leaves_date(self):
		doc = frappe.get_doc({"doctype": "Housing", "housing_name": "NoClean Test", "housing_type": "General"}).insert()
		doc.mark_released()
		self.assertIsNone(doc.last_cleaned_date)
