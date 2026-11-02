import frappe
from frappe.tests import IntegrationTestCase
from frappe_livestock.api.stocking import create_stocking_purchase
from frappe_livestock.api.reporting import batch_gl_entries, batch_pl, feed_timeline, get_ops_snapshot, portfolio


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
		# one seeded scenario every test reads: a batch with head + feed costs
		# and a submitted sale, built through the real APIs
		_ensure_item("Day Old Chick")
		_ensure_item("Layer Feed 50kg")
		_ensure_item("Broiler Bird")

		type_doc = frappe.get_doc("Livestock Type", "Broiler")
		changed = False
		if not type_doc.stocking_item:
			type_doc.stocking_item = "Day Old Chick"
			changed = True
		if not type_doc.finished_item:
			type_doc.finished_item = "Broiler Bird"
			changed = True
		if changed:
			type_doc.save()

		supplier = _supplier()
		warehouse = _warehouse()
		frappe.db.delete("Batch Cost Item", {"batch": "Broiler 2026-08-15"})
		frappe.db.delete("Batch Sale Item", {"batch": "Broiler 2026-08-15"})
		frappe.db.delete("Livestock Batch", {"name": "Broiler 2026-08-15"})

		if not frappe.db.exists("Housing", "Reporting Coop"):
			frappe.get_doc(
				{"doctype": "Housing", "housing_name": "Reporting Coop", "housing_type": "General", "capacity": 1000}
			).insert()
		cls.batch = frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": "2026-08-15",
				"quantity_placed": 500,
				"housing": "Reporting Coop",
			}
		).insert()
		cls.batch_name = cls.batch.name

		create_stocking_purchase(batch=cls.batch_name, supplier=supplier, warehouse=warehouse, rate=1.2)

		from frappe_livestock.api.purchase import create_full_purchase

		feed_buy = create_full_purchase(
			company=frappe.defaults.get_user_default("company"),
			supplier=supplier,
			warehouse=warehouse,
			items=[{"item_code": "Layer Feed 50kg", "qty": 10, "rate": 50}],
		)
		from frappe_livestock.api.allocation import split_purchase_to_batches

		split_purchase_to_batches(
			purchase_invoice=feed_buy["purchase_invoice"],
			allocations=[{"item_code": "Layer Feed 50kg", "batch": cls.batch_name, "qty": 10}],
		)

		cls.batch.db_set("status", "Ready", update_modified=False)

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

		if frappe.db.exists("Batch Sale", cls.sale.name):
			revoke_sale_allocation(cls.sale)
		frappe.db.delete("Batch Cost Item", {"batch": cls.batch_name})
		frappe.db.delete("Batch Sale Item", {"batch": cls.batch_name})
		frappe.db.delete("Livestock Batch", {"name": cls.batch_name})
		super().tearDownClass()

	def test_portfolio_row_has_revenue_and_profit(self):
		rows = portfolio()
		row = next(r for r in rows if r["name"] == self.batch_name)
		self.assertEqual(row["total_cost"], 1100.0)  # 600 head + 500 feed
		self.assertEqual(row["revenue"], 3000.0)  # 100 birds @ 30
		self.assertEqual(row["profit"], 1900.0)
		self.assertAlmostEqual(row["margin"], 1900 / 3000, places=4)
		self.assertEqual(row["remaining"], 400)

	def test_batch_pl_splits_cost_categories(self):
		pl = batch_pl(self.batch_name)
		categories = {row["category"]: row["amount"] for row in pl["costs"]}
		self.assertEqual(categories.get("stocking"), 600.0)
		self.assertEqual(categories.get("Products"), 500.0)  # feed item's item group
		self.assertEqual(pl["totals"]["total_revenue"], 3000.0)
		self.assertEqual(pl["totals"]["profit"], 1900.0)

	def test_batch_gl_entries_join_through_allocations(self):
		rows = batch_gl_entries(self.batch_name)
		self.assertTrue(rows)
		vouchers = {(row.voucher_type, row.voucher_no) for row in rows}
		self.assertIn(("Sales Invoice", self.sale.name), vouchers)  # revenue side
		# every cost-side voucher set has entries
		self.assertTrue(any(v[0] == "Purchase Invoice" for v in vouchers))
		self.assertTrue(any(v[0] == "Payment Entry" for v in vouchers))
		# date filter excludes everything when the window is in the future
		future = batch_gl_entries(self.batch_name, from_date="2999-01-01")
		self.assertEqual(future, [])

	def test_feed_timeline_returns_plain_consumed_row(self):
		frappe.get_doc(
			{
				"doctype": "Feed Event",
				"batch": self.batch_name,
				"feed_item": "Layer Feed 50kg",
				"date": "2026-08-20",
				"qty": 2,
			}
		).insert()
		rows = feed_timeline(batch=self.batch_name)
		match = [r for r in rows if str(r.get("date")) == "2026-08-20"]
		self.assertTrue(match)
		self.assertEqual(float(match[0]["qty"]), 2.0)
		self.assertNotIn("event", match[0])

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


SNAP_TYPE = "Snapshot Broiler"
SNAP_ITEM = "Snapshot Bird"
SNAP_HOUSING = "Snapshot Coop"
SNAP_START = "2026-09-20"
SNAP_OPERATOR_EMAIL = "ops-snapshot-operator@example.com"


def _snapshot_customer():
	name = frappe.db.get_value("Customer", {"customer_name": "Snapshot Customer"}, "name")
	if not name:
		name = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": "Snapshot Customer",
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
				or "All Customer Groups",
				"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name") or "All Territories",
				"customer_type": "Company",
			}
		).insert().name
	return name


class TestOpsSnapshot(IntegrationTestCase):
	"""Task 12: get_ops_snapshot merges summary + feed + weights + P&L in one gated call."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from frappe_livestock.installer import ensure_livestock_roles

		ensure_livestock_roles()
		_ensure_item("Day Old Chick")
		_ensure_item("Layer Feed 50kg")
		_ensure_item(SNAP_ITEM)

		if frappe.db.exists("Livestock Type", SNAP_TYPE):
			type_doc = frappe.get_doc("Livestock Type", SNAP_TYPE)
		else:
			type_doc = frappe.get_doc(
				{
					"doctype": "Livestock Type",
					"livestock_type_name": SNAP_TYPE,
					"stocking_item": "Day Old Chick",
					"finished_item": SNAP_ITEM,
					"stages": [
						{"stage_name": "Starter", "start_day": 0, "end_day": 20},
						{"stage_name": "Grower", "start_day": 21, "end_day": 41},
						{"stage_name": "Finisher", "start_day": 42, "end_day": 48},
					],
				}
			).insert()
		changed = False
		if type_doc.stocking_item != "Day Old Chick":
			type_doc.stocking_item = "Day Old Chick"
			changed = True
		if type_doc.finished_item != SNAP_ITEM:
			type_doc.finished_item = SNAP_ITEM
			changed = True
		if changed:
			type_doc.save()

		if not frappe.db.exists("Housing", SNAP_HOUSING):
			frappe.get_doc(
				{"doctype": "Housing", "housing_name": SNAP_HOUSING, "housing_type": "General", "capacity": 1000}
			).insert()

		batch_name = f"{SNAP_TYPE} {SNAP_START}"
		frappe.db.delete("Batch Cost Item", {"batch": batch_name})
		frappe.db.delete("Batch Sale Item", {"batch": batch_name})
		frappe.db.delete("Livestock Weight", {"batch": batch_name})
		frappe.db.delete("Feed Event", {"batch": batch_name})
		frappe.db.delete("Mortality", {"batch": batch_name})
		frappe.db.delete("Livestock Batch", {"name": batch_name})

		cls.batch = frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": SNAP_TYPE,
				"start_date": SNAP_START,
				"quantity_placed": 500,
				"housing": SNAP_HOUSING,
			}
		).insert()
		cls.batch_name = cls.batch.name

		supplier = _supplier()
		warehouse = _warehouse()
		create_stocking_purchase(batch=cls.batch_name, supplier=supplier, warehouse=warehouse, rate=1.2)

		from frappe_livestock.api.purchase import create_full_purchase

		feed_buy = create_full_purchase(
			company=frappe.defaults.get_user_default("company"),
			supplier=supplier,
			warehouse=warehouse,
			items=[{"item_code": "Layer Feed 50kg", "qty": 10, "rate": 50}],
		)
		from frappe_livestock.api.allocation import split_purchase_to_batches

		split_purchase_to_batches(
			purchase_invoice=feed_buy["purchase_invoice"],
			allocations=[{"item_code": "Layer Feed 50kg", "batch": cls.batch_name, "qty": 10}],
		)

		cls.batch.db_set("status", "Ready", update_modified=False)

		cls.sale = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": frappe.defaults.get_user_default("company"),
				"customer": _snapshot_customer(),
				"items": [
					{
						"item_code": SNAP_ITEM,
						"qty": 100,
						"rate": 30,
						"income_account": frappe.db.get_value(
							"Account",
							{
								"company": frappe.defaults.get_user_default("company"),
								"account_type": "Income",
								"is_group": 0,
							},
							"name",
						),
					}
				],
			}
		)
		cls.sale.insert()
		cls.sale.submit()

	@classmethod
	def tearDownClass(cls):
		from frappe_livestock.api.sales import revoke_sale_allocation

		if frappe.db.exists("Batch Sale", cls.sale.name):
			revoke_sale_allocation(cls.sale)
		frappe.db.delete("Batch Cost Item", {"batch": cls.batch_name})
		frappe.db.delete("Batch Sale Item", {"batch": cls.batch_name})
		frappe.db.delete("Livestock Weight", {"batch": cls.batch_name})
		frappe.db.delete("Feed Event", {"batch": cls.batch_name})
		frappe.db.delete("Mortality", {"batch": cls.batch_name})
		frappe.db.delete("Livestock Batch", {"name": cls.batch_name})
		super().tearDownClass()

	def test_snapshot_merges_summary_and_ops_numbers(self):
		frappe.get_doc(
			{"doctype": "Mortality", "batch": self.batch_name, "date": "2026-10-02", "qty": 25}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Feed Event",
				"batch": self.batch_name,
				"feed_item": "Layer Feed 50kg",
				"date": frappe.utils.today(),
				"qty": 7,
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Feed Event",
				"batch": self.batch_name,
				"feed_item": "Layer Feed 50kg",
				"date": "2026-10-05",
				"qty": 3,
			}
		).insert()
		frappe.get_doc(
			{"doctype": "Livestock Weight", "batch": self.batch_name, "date": "2026-10-01", "average_weight_kg": 1.0}
		).insert()
		frappe.get_doc(
			{"doctype": "Livestock Weight", "batch": self.batch_name, "date": "2026-10-10", "average_weight_kg": 1.6}
		).insert()

		snap = get_ops_snapshot(self.batch_name)

		# summary keys, same math as get_batch_summary
		self.assertEqual(snap["name"], self.batch_name)
		self.assertEqual(snap["livestock_type"], SNAP_TYPE)
		self.assertEqual(snap["quantity_placed"], 500)
		self.assertEqual(snap["mortalities_total"], 25)
		self.assertEqual(snap["surviving"], 475)
		self.assertEqual(snap["sold"], 100)
		self.assertEqual(snap["remaining"], 375)
		self.assertEqual(snap["total_cost"], 1100.0)  # 600 head + 500 feed
		self.assertEqual(snap["status"], "Ready")

		# mortality + feed
		self.assertEqual(snap["mortality_pct"], 0.05)
		self.assertEqual(snap["feed_consumed_today"], 7.0)
		self.assertEqual(snap["feed_consumed_total"], 10.0)
		self.assertEqual(snap["feed_bought_total"], 500.0)  # stocking head excluded

		# weights → honest FCR off the gain
		self.assertEqual(snap["earliest_weight_kg"], 1.0)
		self.assertEqual(snap["earliest_weight_date"], "2026-10-01")
		self.assertEqual(snap["latest_weight_kg"], 1.6)
		self.assertEqual(snap["latest_weight_date"], "2026-10-10")
		self.assertAlmostEqual(snap["weight_gain_kg"], 0.6, places=4)
		self.assertAlmostEqual(snap["fcr"], 10.0 / 0.6, places=4)

		# freshness
		self.assertEqual(snap["last_feed_date"], frappe.utils.today())
		self.assertEqual(snap["last_mortality_date"], "2026-10-02")

		# P&L, same math as _batch_rows for this batch
		self.assertEqual(snap["revenue"], 3000.0)  # 100 birds @ 30
		self.assertEqual(snap["profit"], 1900.0)
		self.assertAlmostEqual(snap["margin"], 1900 / 3000, places=4)

		# readiness
		self.assertIsInstance(snap["days_to_ready"], int)

	def test_snapshot_gated_from_operator(self):
		if frappe.db.exists("User", SNAP_OPERATOR_EMAIL):
			user = frappe.get_doc("User", SNAP_OPERATOR_EMAIL)
			user.set("roles", [{"role": "Livestock Operator"}])
			user.save(ignore_permissions=True)
		else:
			frappe.get_doc(
				{
					"doctype": "User",
					"email": SNAP_OPERATOR_EMAIL,
					"first_name": "Snapshot",
					"roles": [{"role": "Livestock Operator"}],
				}
			).insert(ignore_permissions=True)
		frappe.set_user(SNAP_OPERATOR_EMAIL)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_ops_snapshot(self.batch_name)
		finally:
			frappe.set_user("Administrator")
