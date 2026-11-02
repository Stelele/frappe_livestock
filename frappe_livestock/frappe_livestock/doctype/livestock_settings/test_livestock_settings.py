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
