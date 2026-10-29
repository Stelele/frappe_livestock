import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from frappe_livestock.frappe_livestock.doctype.livestock_type.test_livestock_type import (
	ensure_broiler_type,
)

# Flock's links (chick_purchase_invoice → Purchase Invoice; Livestock Type's item
# links) pull ERPNext's test_purchase_invoice import-time bootstrap, which
# duplicates "Standard Buying" on this site — these tests never need those records.
IGNORE_TEST_RECORD_DEPENDENCIES = ["Item", "Purchase Invoice"]


class TestFlock(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		ensure_broiler_type()
		# IntegrationTestCase rolls back only at class teardown, so the fixed-name
		# doc inserted by test_autoname_is_type_plus_start_date is still present
		# when test_expected_ready_date_is_start_plus_final_stage_end runs.
		if frappe.db.exists("Flock", "Broiler 2026-10-28"):
			frappe.delete_doc("Flock", "Broiler 2026-10-28", force=True)

	def _make(self, start_days_ago=0):
		return frappe.get_doc(
			{
				"doctype": "Flock",
				"livestock_type": "Broiler",
				"start_date": add_days(today(), -start_days_ago),
				"quantity_placed": 500,
			}
		).insert()

	def test_autoname_is_type_plus_start_date(self):
		doc = frappe.get_doc(
			{
				"doctype": "Flock",
				"livestock_type": "Broiler",
				"start_date": "2026-10-28",
				"quantity_placed": 500,
			}
		).insert()
		self.assertEqual(doc.name, "Broiler 2026-10-28")

	def test_stage_and_age_are_computed(self):
		doc = self._make(start_days_ago=25)  # 25 days old -> Grower
		self.assertEqual(doc.age_days(), 25)
		self.assertEqual(doc.stage_name(), "Grower")

	def test_expected_ready_date_is_start_plus_final_stage_end(self):
		doc = frappe.get_doc(
			{
				"doctype": "Flock",
				"livestock_type": "Broiler",
				"start_date": "2026-10-28",
				"quantity_placed": 500,
			}
		).insert()
		self.assertEqual(doc.expected_ready_date().isoformat(), "2026-12-15")  # 48 days later


class TestFlockMortality(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		ensure_broiler_type()
		if frappe.db.exists("Flock", f"Broiler {today()}"):
			frappe.delete_doc("Flock", f"Broiler {today()}", force=True)

	def test_mortality_reduces_surviving_and_remaining(self):
		flock = frappe.get_doc(
			{
				"doctype": "Flock",
				"livestock_type": "Broiler",
				"start_date": today(),
				"quantity_placed": 500,
			}
		).insert()
		frappe.get_doc({"doctype": "Mortality", "flock": flock.name, "qty": 12}).insert()
		self.assertEqual(flock.mortalities_total(), 12)
		self.assertEqual(flock.surviving_birds(), 488)
		self.assertEqual(flock.remaining_birds(), 488)

	def test_mortality_qty_must_be_positive(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			frappe.get_doc({"doctype": "Mortality", "flock": "x", "qty": 0}).insert()

	def test_mortality_qty_zero_against_real_flock(self):
		flock = frappe.get_doc(
			{
				"doctype": "Flock",
				"livestock_type": "Broiler",
				"start_date": today(),
				"quantity_placed": 500,
			}
		).insert()
		with self.assertRaisesRegex(frappe.exceptions.ValidationError, "at least 1"):
			frappe.get_doc({"doctype": "Mortality", "flock": flock.name, "qty": 0}).insert()
