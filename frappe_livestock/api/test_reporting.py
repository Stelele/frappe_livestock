import frappe
from frappe.tests import IntegrationTestCase
from frappe_livestock.api.chicks import create_chick_purchase
from frappe_livestock.api.reporting import flock_gl_entries, flock_pl, portfolio


def _ensure_item(code, group="Products"):
	if not frappe.db.exists("Item", code):
		frappe.get_doc(
			{"doctype": "Item", "item_code": code, "item_group": group, "stock_uom": "Nos", "is_stock_item": 1}
		).insert()
	return code


def _supplier():
	return frappe.db.get_value("Supplier", {"supplier_name": "Hatchery Co"}, "name") or frappe.get_doc(
		{"doctype": "Supplier", "supplier_name": "Hatchery Co", "supplier_group": "All Supplier Groups"}
	).insert().name


def _warehouse():
	company = frappe.defaults.get_user_default("company")
	return frappe.db.get_value(
		"Warehouse", {"company": company, "is_group": 0, "warehouse_name": "Stores"}, "name"
	) or frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")


class TestReporting(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# one seeded scenario every test reads: a flock with chicks + feed costs
		# and a submitted sale, built through the real APIs
		_ensure_item("Day Old Chick")
		_ensure_item("Layer Feed 50kg")
		_ensure_item("Broiler Bird")

		type_doc = frappe.get_doc("Livestock Type", "Broiler")
		changed = False
		if not type_doc.chick_item:
			type_doc.chick_item = "Day Old Chick"
			changed = True
		if not type_doc.finished_item:
			type_doc.finished_item = "Broiler Bird"
			changed = True
		if changed:
			type_doc.save()

		supplier = _supplier()
		warehouse = _warehouse()
		frappe.db.delete("Flock Cost Item", {"flock": "Broiler 2026-08-15"})
		frappe.db.delete("Flock Sale Item", {"flock": "Broiler 2026-08-15"})
		frappe.db.delete("Flock", {"name": "Broiler 2026-08-15"})

		cls.flock = frappe.get_doc(
			{"doctype": "Flock", "livestock_type": "Broiler", "start_date": "2026-08-15", "quantity_placed": 500}
		).insert()
		cls.flock_name = cls.flock.name

		create_chick_purchase(flock=cls.flock_name, supplier=supplier, warehouse=warehouse, rate=1.2)

		from frappe_livestock.api.purchase import create_full_purchase

		feed_buy = create_full_purchase(
			company=frappe.defaults.get_user_default("company"),
			supplier=supplier,
			warehouse=warehouse,
			items=[{"item_code": "Layer Feed 50kg", "qty": 10, "rate": 50}],
		)
		from frappe_livestock.api.allocation import split_purchase_to_flocks

		split_purchase_to_flocks(
			purchase_invoice=feed_buy["purchase_invoice"],
			allocations=[{"item_code": "Layer Feed 50kg", "flock": cls.flock_name, "qty": 10}],
		)

		cls.flock.db_set("status", "Ready", update_modified=False)

		customer = frappe.db.get_value("Customer", {"customer_name": "Hook Customer"}, "name")
		if not customer:
			customer = frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": "Hook Customer",
					"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "All Customer Groups",
					"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name") or "All Territories",
					"customer_type": "Company",
				}
			).insert().name

		cls.sale = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": frappe.defaults.get_user_default("company"),
				"customer": customer,
				"items": [
					{
						"item_code": "Broiler Bird",
						"qty": 100,
						"rate": 30,
						"income_account": frappe.db.get_value(
							"Account", {"company": frappe.defaults.get_user_default("company"), "account_type": "Income", "is_group": 0}, "name"
						),
					}
				],
			}
		)
		cls.sale.insert()
		cls.sale.submit()

	@classmethod
	def tearDownClass(cls):
		# the sale ledger + counter survive rollback only via the API's own writes;
		# revoke through the cancel hook to leave no rows behind
		from frappe_livestock.api.sales import revoke_sale_allocation

		if frappe.db.exists("Flock Sale", cls.sale.name):
			revoke_sale_allocation(cls.sale.name)
		frappe.db.delete("Flock Cost Item", {"flock": cls.flock_name})
		frappe.db.delete("Flock Sale Item", {"flock": cls.flock_name})
		frappe.db.delete("Flock", {"name": cls.flock_name})
		super().tearDownClass()

	def test_portfolio_row_has_revenue_and_profit(self):
		rows = portfolio()
		row = next(r for r in rows if r["name"] == self.flock_name)
		self.assertEqual(row["total_cost"], 1100.0)  # 600 chicks + 500 feed
		self.assertEqual(row["revenue"], 3000.0)  # 100 birds @ 30
		self.assertEqual(row["profit"], 1900.0)
		self.assertAlmostEqual(row["margin"], 1900 / 3000, places=4)
		self.assertEqual(row["remaining_birds"], 400)

	def test_flock_pl_splits_cost_categories(self):
		pl = flock_pl(self.flock_name)
		categories = {row["category"]: row["amount"] for row in pl["costs"]}
		self.assertEqual(categories.get("chicks"), 600.0)
		self.assertEqual(categories.get("Products"), 500.0)  # feed item's item group
		self.assertEqual(pl["totals"]["total_revenue"], 3000.0)
		self.assertEqual(pl["totals"]["profit"], 1900.0)

	def test_flock_gl_entries_join_through_allocations(self):
		rows = flock_gl_entries(self.flock_name)
		self.assertTrue(rows)
		vouchers = {(row.voucher_type, row.voucher_no) for row in rows}
		self.assertIn(("Sales Invoice", self.sale.name), vouchers)  # revenue side
		# every cost-side voucher set has entries
		self.assertTrue(any(v[0] == "Purchase Invoice" for v in vouchers))
		self.assertTrue(any(v[0] == "Payment Entry" for v in vouchers))
		# date filter excludes everything when the window is in the future
		future = flock_gl_entries(self.flock_name, from_date="2999-01-01")
		self.assertEqual(future, [])

	def test_reporting_is_role_gated(self):
		if not frappe.db.exists("User", "nolivestock@example.com"):
			frappe.get_doc(
				{"doctype": "User", "email": "nolivestock@example.com", "first_name": "No", "roles": [{"role": "Employee"}]}
			).insert(ignore_permissions=True)
		frappe.set_user("nolivestock@example.com")
		try:
			with self.assertRaises(frappe.PermissionError):
				portfolio()
		finally:
			frappe.set_user("Administrator")
