import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import get_defaults

from frappe_livestock.api.purchase import cancel_full_purchase, create_full_purchase


class TestFullPurchase(IntegrationTestCase):
	def setUp(self):
		self.company = frappe.defaults.get_user_default("company")
		# IntegrationTestCase rolls back only at class teardown, so guard the
		# fixed-name fixtures against the second test's setUp.
		if frappe.db.exists("Supplier", "FeedCo"):
			self.supplier = "FeedCo"
		else:
			self.supplier = (
				frappe.get_doc(
					{
						"doctype": "Supplier",
						"supplier_name": "FeedCo",
						"supplier_group": "All Supplier Groups",
					}
				)
				.insert()
				.name
			)
		self.warehouse = frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 0}, "name")
		if frappe.db.exists("Item", "Test Feed"):
			self.item = "Test Feed"
		else:
			self.item = (
				frappe.get_doc(
					{
						"doctype": "Item",
						"item_code": "Test Feed",
						"item_group": "Products",
						"stock_uom": "Nos",
						"is_stock_item": 1,
					}
				)
				.insert()
				.name
			)

	def test_creates_four_submitted_docs(self):
		res = create_full_purchase(
			self.company, self.supplier, self.warehouse, [{"item_code": self.item, "qty": 10, "rate": 5}]
		)
		self.assertEqual(frappe.db.get_value("Purchase Order", res["purchase_order"], "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Purchase Receipt", res["purchase_receipt"], "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Purchase Invoice", res["purchase_invoice"], "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Payment Entry", res["payment_entry"], "docstatus"), 1)

	def test_cancel_reverses_chain(self):
		res = create_full_purchase(
			self.company, self.supplier, self.warehouse, [{"item_code": self.item, "qty": 10, "rate": 5}]
		)
		cancel_full_purchase(res["purchase_invoice"])
		self.assertEqual(frappe.db.get_value("Purchase Invoice", res["purchase_invoice"], "docstatus"), 2)
