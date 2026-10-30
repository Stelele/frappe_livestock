import frappe
from frappe.tests import IntegrationTestCase

from frappe_livestock.api.sales import (
	allocate_sales_to_ready_batches,
	allocate_sales_to_ready_batches_for_type,
)
from frappe_livestock.frappe_livestock.doctype.livestock_type.test_livestock_type import (
	ensure_broiler_type,
)


class TestSaleAllocation(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		ensure_broiler_type()
		# IntegrationTestCase rolls back only at class teardown, so clear the
		# fixed-name batches for re-runnability within and across runs.
		for date in ("2026-10-28", "2026-11-14"):
			name = f"Broiler {date}"
			for mortality in frappe.get_all("Mortality", {"batch": name}, pluck="name"):
				frappe.delete_doc("Mortality", mortality, force=True)
			for parent in frappe.get_all("Batch Cost Item", {"batch": name}, pluck="parent"):
				if frappe.db.exists("Batch Cost", parent):
					frappe.delete_doc("Batch Cost", parent, force=True)
			if frappe.db.exists("Livestock Batch", name):
				frappe.delete_doc("Livestock Batch", name, force=True)

	def _ready_batch(self, date, placed=500, sold=0):
		return frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": date,
				"quantity_placed": placed,
				"status": "Ready",
				"sold": sold,
			}
		).insert()

	def test_sales_increment_sold_on_oldest_ready(self):
		older = self._ready_batch("2026-10-28")
		newer = self._ready_batch("2026-11-14")
		# allocate 300 finished-bird units directly (the invoice path is wired in the hook)
		result = allocate_sales_to_ready_batches_for_type(batch_type="Broiler", qty=300)  # noqa: F841 -- kept verbatim per task brief
		older.reload()
		newer.reload()
		self.assertEqual(older.sold, 300)
		self.assertEqual(newer.sold, 0)
		self.assertEqual(older.remaining(), 200)

	def test_over_sale_clamps_at_surviving(self):
		batch = self._ready_batch("2026-10-28", placed=100)
		result = allocate_sales_to_ready_batches_for_type(batch_type="Broiler", qty=150)
		batch.reload()
		self.assertEqual(batch.sold, 100)
		self.assertGreater(result["unallocated"], 0)

	def test_spillover_fills_oldest_first_and_leaves_status(self):
		older = self._ready_batch("2026-10-28", placed=100)
		newer = self._ready_batch("2026-11-14", placed=500)
		result = allocate_sales_to_ready_batches_for_type(batch_type="Broiler", qty=300)
		older.reload()
		newer.reload()
		self.assertEqual(older.sold, 100)
		self.assertEqual(newer.sold, 200)
		self.assertEqual(result, {"allocated": 300, "unallocated": 0})
		self.assertEqual(older.status, "Ready")
		self.assertEqual(newer.status, "Ready")

	def test_non_admin_allocation_increments_sold_only(self):
		# R16: a submitting Sales User has no Livestock Batch permission; allocation must
		# still work and must touch nothing besides `sold`.
		email = "sales-alloc@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc({"doctype": "User", "email": email, "first_name": "Sales Alloc"}).insert()
		batch = self._ready_batch("2026-10-28", placed=500)
		before = {
			"status": batch.status,
			"livestock_type": batch.livestock_type,
			"quantity_placed": batch.quantity_placed,
			"start_date": str(batch.start_date),
		}
		frappe.set_user(email)
		try:
			result = allocate_sales_to_ready_batches_for_type(batch_type="Broiler", qty=100)
		finally:
			frappe.set_user("Administrator")
		batch.reload()
		self.assertEqual(result, {"allocated": 100, "unallocated": 0})
		self.assertEqual(batch.sold, 100)
		# Elevated write must touch nothing besides `sold`.
		self.assertEqual(
			before,
			{
				"status": batch.status,
				"livestock_type": batch.livestock_type,
				"quantity_placed": batch.quantity_placed,
				"start_date": str(batch.start_date),
			},
		)

	def test_no_arg_call_is_explicit_noop(self):
		# R15: without a doc there is no allocation ledger, so a sweep would
		# double-count; the no-arg call must be a no-op.
		self.assertEqual(allocate_sales_to_ready_batches(), {"allocated": 0, "unallocated": 0})

	def test_submit_hook_allocates_finished_item_to_ready_batch(self):
		# End-to-end: Sales Invoice on_submit hook -> FIFO allocation.
		# Uses a dedicated Livestock Type + item so the shared Broiler is untouched.
		if frappe.db.exists("Item", "Hook Bird"):
			item = "Hook Bird"
		else:
			item = (
				frappe.get_doc(
					{
						"doctype": "Item",
						"item_code": "Hook Bird",
						"item_group": "Products",
						"stock_uom": "Nos",
						"is_stock_item": 0,
						"is_sales_item": 1,
					}
				)
				.insert()
				.name
			)
		if frappe.db.exists("Livestock Type", "Broiler Hook Test"):
			frappe.db.set_value("Livestock Type", "Broiler Hook Test", "finished_item", item)
		else:
			frappe.get_doc(
				{
					"doctype": "Livestock Type",
					"livestock_type_name": "Broiler Hook Test",
					"finished_item": item,
					"stages": [
						{"stage_name": "Day Old Chick", "start_day": 0, "end_day": 20},
						{"stage_name": "Grower", "start_day": 21, "end_day": 41},
						{"stage_name": "Broiler", "start_day": 42, "end_day": 48},
					],
				}
			).insert(ignore_if_duplicate=True)
		batch_name = "Broiler Hook Test 2026-10-28"
		if frappe.db.exists("Livestock Batch", batch_name):
			frappe.delete_doc("Livestock Batch", batch_name, force=True)
		batch = frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler Hook Test",
				"start_date": "2026-10-28",
				"quantity_placed": 500,
				"status": "Ready",
				"sold": 0,
			}
		).insert()
		if frappe.db.exists("Customer", "Hook Customer"):
			customer = "Hook Customer"
		else:
			# "All Customer Groups" / "All Territories" are group nodes and are
			# rejected on Customer; pick leaf nodes (guarded, site-seeded).
			customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "Individual"
			territory = frappe.db.get_value("Territory", {"is_group": 0}, "name") or "Zimbabwe"
			customer = (
				frappe.get_doc(
					{
						"doctype": "Customer",
						"customer_name": "Hook Customer",
						"customer_group": customer_group,
						"territory": territory,
					}
				)
				.insert()
				.name
			)
		company = frappe.defaults.get_user_default("company")
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": company,
				"customer": customer,
				"items": [{"item_code": item, "qty": 3, "rate": 10}],
			}
		)
		si.insert()
		si.submit()
		batch.reload()
		self.assertEqual(batch.sold, 3)
		self.assertEqual(batch.status, "Ready")
