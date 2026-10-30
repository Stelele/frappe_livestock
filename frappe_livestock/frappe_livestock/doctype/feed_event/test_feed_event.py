import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from frappe_livestock.frappe_livestock.doctype.livestock_type.test_livestock_type import (
	ensure_broiler_type,
)

# see test_livestock_batch.py: the Item/Purchase Invoice link walk trips ERPNext's bootstrap
IGNORE_TEST_RECORD_DEPENDENCIES = ["Item", "Purchase Invoice"]

FEED_ITEM_CODE = "Early Lay Feed"

# The `feed_item` Link pulls Item (and its whole ERPNext fixture chain,
# whose import-time bootstrap conflicts with existing dev-site data) into
# automatic test-record generation. These tests create their own Item record.
IGNORE_TEST_RECORD_DEPENDENCIES = ["Item"]


def ensure_feed_item():
	if not frappe.db.exists("Item", FEED_ITEM_CODE):
		if not frappe.db.exists("Item Group", "Products"):
			frappe.get_doc(
				{
					"doctype": "Item Group",
					"item_group_name": "Products",
					"is_group": 0,
				}
			).insert(ignore_if_duplicate=True)
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": FEED_ITEM_CODE,
				"item_name": FEED_ITEM_CODE,
				"item_group": "Products",
				"stock_uom": "Nos",
				"is_stock_item": 1,
			}
		).insert(ignore_if_duplicate=True)


class TestFeedEvent(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		ensure_broiler_type()
		ensure_feed_item()
		if frappe.db.exists("Livestock Batch", f"Broiler {today()}"):
			frappe.delete_doc("Livestock Batch", f"Broiler {today()}", force=True)

	def test_feed_event_saves(self):
		batch = frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": today(),
				"quantity_placed": 500,
			}
		).insert()
		doc = frappe.get_doc(
			{
				"doctype": "Feed Event",
				"batch": batch.name,
				"feed_item": FEED_ITEM_CODE,
				"event": "Open",
				"qty": 1,
			}
		).insert()
		self.assertEqual(doc.event, "Open")
