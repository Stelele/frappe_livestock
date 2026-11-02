import frappe
from frappe.tests import IntegrationTestCase
from frappe_livestock.api.stocking import create_stocking_purchase, link_stocking_purchase


def _ensure_item(code):
	if not frappe.db.exists("Item", code):
		frappe.get_doc(
			{"doctype": "Item", "item_code": code, "item_group": "Products", "stock_uom": "Nos", "is_stock_item": 1}
		).insert()
	return code


def _ensure_supplier():
	name = frappe.db.get_value("Supplier", {"supplier_name": "Hatchery Co"}, "name")
	return name or frappe.get_doc(
		{"doctype": "Supplier", "supplier_name": "Hatchery Co", "supplier_group": "All Supplier Groups"}
	).insert().name


def _warehouse():
	company = frappe.defaults.get_user_default("company")
	return frappe.db.get_value(
		"Warehouse", {"company": company, "is_group": 0, "warehouse_name": "Stores"}, "name"
	) or frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")


def _purchase(items):
	from frappe_livestock.api.purchase import create_full_purchase

	return create_full_purchase(
		company=frappe.defaults.get_user_default("company"),
		supplier=_ensure_supplier(),
		warehouse=_warehouse(),
		items=items,
	)


class TestStockingCost(IntegrationTestCase):
	def setUp(self):
		_ensure_item("Day Old Chick")
		_ensure_item("Feed 50kg")
		type_doc = frappe.get_doc("Livestock Type", "Broiler")
		if not type_doc.stocking_item:
			type_doc.stocking_item = "Day Old Chick"
			type_doc.save()

		self.supplier = _ensure_supplier()
		self.warehouse = _warehouse()
		if frappe.db.exists("Housing", "Test Coop"):
			frappe.delete_doc("Housing", "Test Coop", force=True)
		self.housing = frappe.get_doc(
			{"doctype": "Housing", "housing_name": "Test Coop", "housing_type": "General", "capacity": 1000}
		).insert()
		self.batch_name = f"Broiler {frappe.utils.today()}"
		# the purchase chain commits internally, so docs from earlier runs can
		# survive the test rollback — clear this batch's rows before re-inserting
		frappe.db.delete("Batch Cost Item", {"batch": self.batch_name})
		frappe.db.delete("Mortality", {"batch": self.batch_name})
		frappe.db.delete("Livestock Batch", {"name": self.batch_name})
		self.batch = frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": frappe.utils.today(),
				"quantity_placed": 500,
				"housing": self.housing.name,
			}
		).insert()

	def _housed_batch(self, placed, capacity):
		housing = frappe.get_doc(
			{
				"doctype": "Housing",
				"housing_name": f"Test Coop {placed}-{capacity}-{frappe.generate_hash(length=6)}",
				"housing_type": "General",
				"capacity": capacity,
			}
		).insert()
		return frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": frappe.utils.today(),
				"quantity_placed": placed,
				"housing": housing.name,
			}
		).insert()

	def test_create_stocking_purchase_costs_the_batch(self):
		result = create_stocking_purchase(
			batch=self.batch_name, supplier=self.supplier, warehouse=self.warehouse, rate=1.2
		)
		self.batch.reload()
		self.assertEqual(self.batch.stocking_purchase_invoice, result["purchase_invoice"])
		self.assertEqual(self.batch.total_cost(), 600.0)  # 500 head @ 1.20
		self.assertEqual(self.batch.cost_per_head(), 1.2)

	def test_link_existing_invoice(self):
		made = _purchase([{"item_code": "Day Old Chick", "qty": 300, "rate": 1.0}])
		result = link_stocking_purchase(batch=self.batch_name, purchase_invoice=made["purchase_invoice"])
		self.batch.reload()
		self.assertEqual(self.batch.stocking_purchase_invoice, made["purchase_invoice"])
		self.assertEqual(self.batch.total_cost(), 300.0)  # invoice line qty 300 @ 1.00

	def test_invoice_without_stocking_item_is_rejected(self):
		made = _purchase([{"item_code": "Feed 50kg", "qty": 5, "rate": 40}])
		with self.assertRaisesRegex(frappe.exceptions.ValidationError, "has no"):
			link_stocking_purchase(batch=self.batch_name, purchase_invoice=made["purchase_invoice"])

	def test_stocking_requires_housing(self):
		batch = frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": frappe.utils.today(),
				"quantity_placed": 500,
			}
		).insert()
		with self.assertRaisesRegex(frappe.exceptions.ValidationError, "Set a Housing"):
			create_stocking_purchase(
				batch=batch.name, supplier=self.supplier, warehouse=self.warehouse, rate=1.0
			)

	def test_stocking_checks_capacity(self):
		tight = self._housed_batch(placed=500, capacity=100)
		with self.assertRaisesRegex(frappe.exceptions.ValidationError, "exceeds housing capacity"):
			create_stocking_purchase(
				batch=tight.name, supplier=self.supplier, warehouse=self.warehouse, rate=1.0
			)
		# capacity 0 means unlimited — 500 head passes
		open_house = self._housed_batch(placed=500, capacity=0)
		result = create_stocking_purchase(
			batch=open_house.name, supplier=self.supplier, warehouse=self.warehouse, rate=1.0
		)
		self.assertEqual(
			frappe.db.get_value("Livestock Batch", open_house.name, "stocking_purchase_invoice"),
			result["purchase_invoice"],
		)

	def test_stocking_marks_housing_occupied(self):
		self.assertEqual(frappe.db.get_value("Housing", self.housing.name, "status"), "Ready")
		create_stocking_purchase(
			batch=self.batch_name, supplier=self.supplier, warehouse=self.warehouse, rate=1.2
		)
		self.assertEqual(frappe.db.get_value("Housing", self.housing.name, "status"), "Occupied")
