"""PIT for Task 2: Livestock Manager + Livestock Operator roles.

Operator (only role): can insert Feed Event + Mortality, can list
Livestock Batch, but CANNOT delete Feed Event rows or write to the batch.
Manager (only role): the reporting portfolio endpoint round-trips
(DASHBOARD_ROLES gate accepts Manager) and batch_pl — which joins the
ERPNext Item doctype — runs without PermissionError. A user with NEITHER
livestock role is rejected by the reporting gate.

All fixtures are test-local: type "Broiler Roles Test" (+ its batch and
children) belongs to this module alone, so nothing shared is ever deleted.
"""

import frappe
from frappe.tests import IntegrationTestCase

from frappe_livestock.api.reporting import batch_pl, portfolio
from frappe_livestock.installer import ensure_livestock_roles

OPERATOR_EMAIL = "livestock-operator@example.com"
MANAGER_EMAIL = "livestock-manager@example.com"
NOROLE_EMAIL = "livestock-norole@example.com"
TYPE_NAME = "Broiler Roles Test"
COST_PI = "ROLE-TEST-PI"


def _ensure_user(email, role):
	"""Create the user with exactly `role`, or reset an existing user's
	roles to exactly `role` (re-runs and aborted runs must not leak roles)."""
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
		user.set("roles", [{"role": role}])
		user.save(ignore_permissions=True)
	else:
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
		_ensure_user(NOROLE_EMAIL, "Employee")

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

		if not frappe.db.exists("Livestock Type", TYPE_NAME):
			frappe.get_doc(
				{
					"doctype": "Livestock Type",
					"livestock_type_name": TYPE_NAME,
					"stages": [
						{"stage_name": "Day Old Chick", "start_day": 0, "end_day": 20},
						{"stage_name": "Grower", "start_day": 21, "end_day": 41},
						{"stage_name": "Broiler", "start_day": 42, "end_day": 48},
					],
				}
			).insert(ignore_if_duplicate=True)

		cls._clear_fixtures()
		cls.batch = frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": TYPE_NAME,
				"start_date": "2026-09-01",
				"quantity_placed": 100,
			}
		).insert()
		cls.batch_name = cls.batch.name

		# One cost row so batch_pl exercises the ERPNext Item join
		# (the empty-cost path never touches Item). purchase_invoice is a
		# throwaway name, not a real invoice — ignore_links skips the Link
		# check; permission routing is what this test pins.
		cost = frappe.get_doc(
			{
				"doctype": "Batch Cost",
				"purchase_invoice": COST_PI,
				"posting_date": "2026-09-05",
				"items": [
					{"item_code": "Layer Feed 50kg", "qty": 10, "amount": 500, "batch": cls.batch_name}
				],
			}
		)
		cost.flags.ignore_links = True
		cost.insert(ignore_permissions=True)

	@classmethod
	def _clear_fixtures(cls):
		# Children before parents; scoped to this module's type so shared
		# batches (e.g. "Broiler 2026-09-01") are never touched.
		names = frappe.get_all("Livestock Batch", {"livestock_type": TYPE_NAME}, pluck="name")
		for name in names:
			for parent in frappe.get_all("Batch Cost Item", {"batch": name}, pluck="parent"):
				if frappe.db.exists("Batch Cost", parent):
					frappe.delete_doc("Batch Cost", parent, force=True)
			frappe.db.delete("Feed Event", {"batch": name})
			frappe.db.delete("Mortality", {"batch": name})
			frappe.delete_doc("Livestock Batch", name, force=True)

	@classmethod
	def tearDownClass(cls):
		cls._clear_fixtures()
		for email in (OPERATOR_EMAIL, MANAGER_EMAIL, NOROLE_EMAIL):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email)  # cascades Has Role children
		super().tearDownClass()

	def test_operator_can_insert_feed_event(self):
		frappe.set_user(OPERATOR_EMAIL)
		try:
			doc = frappe.get_doc(
				{
					"doctype": "Feed Event",
					"batch": self.batch_name,
					"feed_item": "Layer Feed 50kg",
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

	def test_operator_cannot_write_batch(self):
		frappe.set_user(OPERATOR_EMAIL)
		try:
			doc = frappe.get_doc("Livestock Batch", self.batch_name)
			doc.quantity_placed = 999
			with self.assertRaises(frappe.PermissionError):
				doc.save()
		finally:
			frappe.set_user("Administrator")

	def test_manager_can_run_portfolio(self):
		frappe.set_user(MANAGER_EMAIL)
		try:
			rows = portfolio()
			self.assertTrue(any(r["name"] == self.batch_name for r in rows))
		finally:
			frappe.set_user("Administrator")

	def test_manager_can_run_batch_pl_with_cost_row(self):
		# batch_pl joins ERPNext Item for cost categories — reachable for
		# Manager only via the REPORTING_PERMISSIONS read grant.
		frappe.set_user(MANAGER_EMAIL)
		try:
			pl = batch_pl(self.batch_name)
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(pl["costs"])
		self.assertEqual(pl["totals"]["total_cost"], 500.0)

	def test_user_without_livestock_role_rejected_by_gate(self):
		frappe.set_user(NOROLE_EMAIL)
		try:
			with self.assertRaises(frappe.PermissionError):
				portfolio()
		finally:
			frappe.set_user("Administrator")
