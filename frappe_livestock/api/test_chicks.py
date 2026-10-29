import frappe
from frappe.tests import IntegrationTestCase
from frappe_livestock.api.chicks import create_chick_purchase, link_chick_purchase


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


class TestChickCost(IntegrationTestCase):
	def setUp(self):
		_ensure_item("Day Old Chick")
		_ensure_item("Feed 50kg")
		type_doc = frappe.get_doc("Livestock Type", "Broiler")
		if not type_doc.chick_item:
			type_doc.chick_item = "Day Old Chick"
			type_doc.save()

		self.supplier = _ensure_supplier()
		self.warehouse = _warehouse()
		self.flock_name = f"Broiler {frappe.utils.today()}"
		# the purchase chain commits internally, so docs from earlier runs can
		# survive the test rollback — clear this flock's rows before re-inserting
		frappe.db.delete("Flock Cost Item", {"flock": self.flock_name})
		frappe.db.delete("Mortality", {"flock": self.flock_name})
		frappe.db.delete("Flock", {"name": self.flock_name})
		self.flock = frappe.get_doc(
			{"doctype": "Flock", "livestock_type": "Broiler", "start_date": frappe.utils.today(), "quantity_placed": 500}
		).insert()

	def test_create_chick_purchase_costs_the_flock(self):
		result = create_chick_purchase(
			flock=self.flock_name, supplier=self.supplier, warehouse=self.warehouse, rate=1.2
		)
		self.flock.reload()
		self.assertEqual(self.flock.chick_purchase_invoice, result["purchase_invoice"])
		self.assertEqual(self.flock.total_cost(), 600.0)  # 500 chicks @ 1.20
		self.assertEqual(self.flock.cost_per_bird(), 1.2)

	def test_link_existing_invoice(self):
		made = _purchase([{"item_code": "Day Old Chick", "qty": 300, "rate": 1.0}])
		result = link_chick_purchase(flock=self.flock_name, purchase_invoice=made["purchase_invoice"])
		self.flock.reload()
		self.assertEqual(self.flock.chick_purchase_invoice, made["purchase_invoice"])
		self.assertEqual(self.flock.total_cost(), 300.0)  # invoice line qty 300 @ 1.00

	def test_invoice_without_chick_item_is_rejected(self):
		made = _purchase([{"item_code": "Feed 50kg", "qty": 5, "rate": 40}])
		with self.assertRaisesRegex(frappe.exceptions.ValidationError, "has no"):
			link_chick_purchase(flock=self.flock_name, purchase_invoice=made["purchase_invoice"])
