import frappe
from frappe.tests import IntegrationTestCase

from frappe_livestock.api.settings import get_purchase_context

# Livestock Settings links ERPNext core (Mode of Payment, Warehouse) whose
# test modules bootstrap site-wide records (Price Lists, ...) that already
# exist on the dev site. Like mortality's Item exclusion, skip auto record
# generation for them — the tests below build their own fixtures.
IGNORE_TEST_RECORD_DEPENDENCIES = ["Mode of Payment", "Warehouse"]


def _ensure_settings_test_mop():
	existing = frappe.db.get_list("Mode of Payment", pluck="name", limit=1)
	if existing:
		return existing[0]
	return frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": "Settings Test MoP"}).insert().name


def _ensure_settings_test_warehouse(company):
	name = "Settings Test Warehouse"
	for wh in frappe.db.get_list("Warehouse", filters={"company": company}, pluck="name"):
		if "Settings Test Warehouse" in wh:
			return wh
	if frappe.db.exists("Warehouse", name):
		return name
	return (
		frappe.get_doc({"doctype": "Warehouse", "warehouse_name": name, "company": company})
		.insert()
		.name
	)


def _ensure_settings_test_group_warehouse(company):
	name = "Settings Test Group Warehouse"
	rows = frappe.db.get_list(
		"Warehouse", filters={"warehouse_name": name, "company": company}, pluck="name"
	)
	if rows:
		return rows[0]
	return (
		frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": name,
				"company": company,
				"is_group": 1,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class TestLivestockSettings(IntegrationTestCase):
	def setUp(self):
		self.company = frappe.defaults.get_user_default("company")
		self.mop = _ensure_settings_test_mop()
		self.warehouse = _ensure_settings_test_warehouse(self.company)
		settings = frappe.get_single("Livestock Settings")
		self._orig_mop = settings.mode_of_payment
		self._orig_wh = settings.default_warehouse

	def tearDown(self):
		settings = frappe.get_single("Livestock Settings")
		settings.mode_of_payment = self._orig_mop
		settings.default_warehouse = self._orig_wh
		settings.save(ignore_permissions=True)

	def test_settings_save_roundtrip(self):
		settings = frappe.get_single("Livestock Settings")
		settings.mode_of_payment = self.mop
		settings.default_warehouse = self.warehouse
		settings.save()
		reloaded = frappe.get_single("Livestock Settings")
		self.assertEqual(reloaded.mode_of_payment, self.mop)
		self.assertEqual(reloaded.default_warehouse, self.warehouse)

	def test_get_purchase_context_returns_settings_values(self):
		settings = frappe.get_single("Livestock Settings")
		settings.mode_of_payment = self.mop
		settings.default_warehouse = self.warehouse
		settings.save(ignore_permissions=True)
		ctx = get_purchase_context()
		self.assertEqual(ctx["company"], self.company)
		self.assertEqual(ctx["warehouse"], self.warehouse)
		self.assertEqual(ctx["mode_of_payment"], self.mop)
		self.assertIn("warnings", ctx)
		self.assertIsInstance(ctx["warnings"], list)

	def test_get_purchase_context_no_company_warning(self):
		ctx = get_purchase_context(company="")
		self.assertFalse(ctx["company"])
		self.assertIsNone(ctx["warehouse"])
		self.assertTrue(ctx["warnings"])
		self.assertTrue(any("No company default" in w for w in ctx["warnings"]))
		self.assertTrue(any("company" in w for w in ctx["warnings"]))

	def test_sole_leaf_warehouse_fallback(self):
		frappe.db.set_single_value("Livestock Settings", "default_warehouse", None)
		leaf = frappe.get_all(
			"Warehouse", filters={"company": self.company, "is_group": 0}, pluck="name"
		)
		if len(leaf) != 1:
			self.skipTest("multi-warehouse dev site")
		ctx = get_purchase_context(company=self.company)
		self.assertEqual(ctx["warehouse"], leaf[0])

	def test_missing_mop_warns_and_returns_none(self):
		frappe.db.set_single_value(
			"Livestock Settings", "mode_of_payment", "Settings Test Missing MoP"
		)
		ctx = get_purchase_context(company=self.company)
		self.assertIsNone(ctx["mode_of_payment"])
		self.assertTrue(
			any("Settings Test Missing MoP" in w for w in ctx["warnings"])
		)

	def test_missing_default_warehouse_warns_and_returns_none(self):
		frappe.db.set_single_value(
			"Livestock Settings", "default_warehouse", "Settings Missing Warehouse"
		)
		ctx = get_purchase_context(company=self.company)
		self.assertIsNone(ctx["warehouse"])
		self.assertTrue(
			any("Settings Missing Warehouse" in w for w in ctx["warnings"])
		)

	def test_group_default_warehouse_warns_and_returns_none(self):
		group_wh = _ensure_settings_test_group_warehouse(self.company)
		frappe.db.set_single_value(
			"Livestock Settings", "default_warehouse", group_wh
		)
		ctx = get_purchase_context(company=self.company)
		self.assertIsNone(ctx["warehouse"])
		self.assertTrue(any(group_wh in w for w in ctx["warnings"]))

	def test_other_company_default_warehouse_warns_and_returns_none(self):
		companies = frappe.get_all("Company", pluck="name")
		others = [c for c in companies if c != self.company]
		if not others:
			self.skipTest("single-company dev site")
		frappe.db.set_single_value(
			"Livestock Settings", "default_warehouse", self.warehouse
		)
		ctx = get_purchase_context(company=others[0])
		self.assertIsNone(ctx["warehouse"])
		self.assertTrue(any(self.warehouse in w for w in ctx["warnings"]))

	def test_cash_fallback_when_settings_unset(self):
		if not frappe.db.exists("Mode of Payment", "Cash"):
			self.skipTest("no Cash Mode of Payment on dev site")
		frappe.db.set_single_value("Livestock Settings", "mode_of_payment", None)
		ctx = get_purchase_context(company=self.company)
		self.assertEqual(ctx["mode_of_payment"], "Cash")
		self.assertFalse(any("Mode of Payment" in w for w in ctx["warnings"]))
