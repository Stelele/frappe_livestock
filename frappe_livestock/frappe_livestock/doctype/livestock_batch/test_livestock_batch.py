import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from frappe_livestock.frappe_livestock.doctype.livestock_type.test_livestock_type import (
	ensure_broiler_type,
)
from frappe_livestock.installer import ensure_livestock_roles

# Livestock Batch's links (stocking_purchase_invoice → Purchase Invoice; Livestock Type's item
# links) pull ERPNext's test_purchase_invoice import-time bootstrap, which
# duplicates "Standard Buying" on this site — these tests never need those records.
IGNORE_TEST_RECORD_DEPENDENCIES = ["Item", "Purchase Invoice"]

BATCH_MANAGER_EMAIL = "livestock-batch-manager@example.com"


def _ensure_batch_manager():
	ensure_livestock_roles()
	if frappe.db.exists("User", BATCH_MANAGER_EMAIL):
		user = frappe.get_doc("User", BATCH_MANAGER_EMAIL)
		user.set("roles", [{"role": "Livestock Manager"}])
		user.save(ignore_permissions=True)
	else:
		frappe.get_doc(
			{
				"doctype": "User",
				"email": BATCH_MANAGER_EMAIL,
				"first_name": "livestock-batch-manager",
				"roles": [{"role": "Livestock Manager"}],
			}
		).insert(ignore_permissions=True)


class TestLivestockBatch(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		ensure_broiler_type()
		# IntegrationTestCase rolls back only at class teardown, so the fixed-name
		# doc inserted by test_autoname_is_type_plus_start_date is still present
		# when test_expected_ready_date_is_start_plus_final_stage_end runs.
		for name in ("Broiler 2026-10-28", "Broiler 2026-10-28 2", "Broiler 2026-10-28 3"):
			if frappe.db.exists("Livestock Batch", name):
				frappe.delete_doc("Livestock Batch", name, force=True)

	def _make(self, start_days_ago=0):
		return frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": add_days(today(), -start_days_ago),
				"quantity_placed": 500,
			}
		).insert()

	def test_autoname_is_type_plus_start_date(self):
		doc = frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": "2026-10-28",
				"quantity_placed": 500,
			}
		).insert()
		self.assertEqual(doc.name, "Broiler 2026-10-28")

	def test_autoname_disambiguates_same_day_batches(self):
		first = frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": "2026-10-28",
				"quantity_placed": 500,
			}
		).insert()
		second = frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": "2026-10-28",
				"quantity_placed": 500,
			}
		).insert()
		third = frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": "2026-10-28",
				"quantity_placed": 500,
			}
		).insert()
		self.assertEqual(first.name, "Broiler 2026-10-28")
		self.assertEqual(second.name, "Broiler 2026-10-28 2")
		self.assertEqual(third.name, "Broiler 2026-10-28 3")

	def test_sold_adopts_db_value_on_save(self):
		batch = frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": "2026-10-28",
				"quantity_placed": 500,
			}
		).insert()
		# a concurrent sale writes `sold` directly to the DB; a save of a doc
		# loaded before that adopts the DB value instead of failing
		frappe.db.set_value("Livestock Batch", batch.name, "sold", 2)
		batch.sold = 0
		batch.save()
		self.assertEqual(frappe.db.get_value("Livestock Batch", batch.name, "sold"), 2)

	def test_quantity_placed_is_set_only_once(self):
		_ensure_batch_manager()
		batch = frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": "2026-10-28",
				"quantity_placed": 500,
			}
		).insert()
		frappe.set_user(BATCH_MANAGER_EMAIL)
		try:
			doc = frappe.get_doc("Livestock Batch", batch.name)
			doc.quantity_placed = 600
			with self.assertRaises(frappe.exceptions.ValidationError):
				doc.save()
		finally:
			frappe.set_user("Administrator")

	def test_stage_and_age_are_computed(self):
		doc = self._make(start_days_ago=25)  # 25 days old -> Grower
		self.assertEqual(doc.age_days(), 25)
		self.assertEqual(doc.stage_name(), "Grower")

	def test_expected_ready_date_is_start_plus_final_stage_end(self):
		doc = frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": "2026-10-28",
				"quantity_placed": 500,
			}
		).insert()
		self.assertEqual(doc.expected_ready_date().isoformat(), "2026-12-15")  # 48 days later


class TestLivestockBatchMortality(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		ensure_broiler_type()
		if frappe.db.exists("Livestock Batch", f"Broiler {today()}"):
			frappe.delete_doc("Livestock Batch", f"Broiler {today()}", force=True)

	def test_mortality_reduces_surviving_and_remaining(self):
		batch = frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": today(),
				"quantity_placed": 500,
			}
		).insert()
		frappe.get_doc({"doctype": "Mortality", "batch": batch.name, "qty": 12}).insert()
		self.assertEqual(batch.mortalities_total(), 12)
		self.assertEqual(batch.surviving(), 488)
		self.assertEqual(batch.remaining(), 488)

	def test_mortality_qty_must_be_positive(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			frappe.get_doc({"doctype": "Mortality", "batch": "x", "qty": 0}).insert()

	def test_mortality_qty_zero_against_real_batch(self):
		batch = frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": today(),
				"quantity_placed": 500,
			}
		).insert()
		with self.assertRaisesRegex(frappe.exceptions.ValidationError, "at least 1"):
			frappe.get_doc({"doctype": "Mortality", "batch": batch.name, "qty": 0}).insert()
