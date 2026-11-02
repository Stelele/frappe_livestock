"""PIT for Task 2: Livestock Manager + Livestock Operator roles.

Operator (only role): can insert Feed Event + Mortality, can list
Livestock Batch, but CANNOT delete. Manager (only role): the reporting
portfolio endpoint round-trips (DASHBOARD_ROLES gate accepts Manager).
"""

import frappe
from frappe.tests import IntegrationTestCase

from frappe_livestock.api.reporting import portfolio
from frappe_livestock.installer import ensure_livestock_roles

OPERATOR_EMAIL = "livestock-operator@example.com"
MANAGER_EMAIL = "livestock-manager@example.com"


def _ensure_user(email, role):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"roles": [{"role": role}],
			}
		).insert(ignore_permissions=True)


class TestRoles(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_livestock_roles()
		_ensure_user(OPERATOR_EMAIL, "Livestock Operator")
		_ensure_user(MANAGER_EMAIL, "Livestock Manager")

		if not frappe.db.exists("Item", "Layer Feed 50kg"):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": "Layer Feed 50kg",
					"item_group": "Products",
					"stock_uom": "Nos",
					"is_stock_item": 1,
				}
			).insert()

		frappe.db.delete("Feed Event", {"batch": "Broiler 2026-09-01"})
		frappe.db.delete("Mortality", {"batch": "Broiler 2026-09-01"})
		frappe.db.delete("Livestock Batch", {"name": "Broiler 2026-09-01"})
		cls.batch = frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": "2026-09-01",
				"quantity_placed": 100,
			}
		).insert()
		cls.batch_name = cls.batch.name

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete("Feed Event", {"batch": cls.batch_name})
		frappe.db.delete("Mortality", {"batch": cls.batch_name})
		frappe.db.delete("Livestock Batch", {"name": cls.batch_name})
		super().tearDownClass()

	def test_operator_can_insert_feed_event(self):
		frappe.set_user(OPERATOR_EMAIL)
		try:
			doc = frappe.get_doc(
				{
					"doctype": "Feed Event",
					"batch": self.batch_name,
					"feed_item": "Layer Feed 50kg",
					"event": "Open",
					"date": "2026-09-02",
					"qty": 5,
				}
			).insert()
			self.assertTrue(doc.name)
		finally:
			frappe.set_user("Administrator")

	def test_operator_can_insert_mortality(self):
		frappe.set_user(OPERATOR_EMAIL)
		try:
			doc = frappe.get_doc(
				{
					"doctype": "Mortality",
					"batch": self.batch_name,
					"date": "2026-09-03",
					"qty": 2,
				}
			).insert()
			self.assertTrue(doc.name)
		finally:
			frappe.set_user("Administrator")

	def test_operator_can_read_batch_but_cannot_delete(self):
		feed = frappe.get_doc(
			{
				"doctype": "Feed Event",
				"batch": self.batch_name,
				"feed_item": "Layer Feed 50kg",
				"event": "Finish",
				"date": "2026-09-04",
				"qty": 1,
			}
		).insert()
		frappe.set_user(OPERATOR_EMAIL)
		try:
			rows = frappe.get_list("Livestock Batch")
			self.assertTrue(any(r.name == self.batch_name for r in rows))
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc("Feed Event", feed.name).delete()
		finally:
			frappe.set_user("Administrator")

	def test_manager_can_run_portfolio(self):
		frappe.set_user(MANAGER_EMAIL)
		try:
			rows = portfolio()
			self.assertTrue(any(r["name"] == self.batch_name for r in rows))
		finally:
			frappe.set_user("Administrator")
