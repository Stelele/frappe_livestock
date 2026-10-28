import frappe
from frappe.tests import IntegrationTestCase

from frappe_livestock.api.sales import allocate_sales_to_ready_flocks_for_type
from frappe_livestock.frappe_livestock.doctype.livestock_type.test_livestock_type import (
	ensure_broiler_type,
)


class TestSaleAllocation(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		ensure_broiler_type()
		# IntegrationTestCase rolls back only at class teardown, so clear the
		# fixed-name flocks for re-runnability within and across runs.
		for date in ("2026-10-28", "2026-11-14"):
			name = f"Broiler {date}"
			for mortality in frappe.get_all("Mortality", {"flock": name}, pluck="name"):
				frappe.delete_doc("Mortality", mortality, force=True)
			for parent in frappe.get_all("Flock Cost Item", {"flock": name}, pluck="parent"):
				if frappe.db.exists("Flock Cost", parent):
					frappe.delete_doc("Flock Cost", parent, force=True)
			if frappe.db.exists("Flock", name):
				frappe.delete_doc("Flock", name, force=True)

	def _ready_flock(self, date, placed=500, sold=0):
		return frappe.get_doc(
			{
				"doctype": "Flock",
				"livestock_type": "Broiler",
				"start_date": date,
				"quantity_placed": placed,
				"status": "Ready",
				"birds_sold": sold,
			}
		).insert()

	def test_sales_increment_birds_sold_on_oldest_ready(self):
		older = self._ready_flock("2026-10-28")
		newer = self._ready_flock("2026-11-14")
		# allocate 300 finished-bird units directly (the invoice path is wired in the hook)
		result = allocate_sales_to_ready_flocks_for_type(flock_type="Broiler", qty=300)  # noqa: F841 -- kept verbatim per task brief
		older.reload()
		newer.reload()
		self.assertEqual(older.birds_sold, 300)
		self.assertEqual(newer.birds_sold, 0)
		self.assertEqual(older.remaining_birds(), 200)

	def test_over_sale_clamps_at_surviving(self):
		flock = self._ready_flock("2026-10-28", placed=100)
		result = allocate_sales_to_ready_flocks_for_type(flock_type="Broiler", qty=150)
		flock.reload()
		self.assertEqual(flock.birds_sold, 100)
		self.assertGreater(result["unallocated"], 0)

	def test_spillover_fills_oldest_first_and_leaves_status(self):
		older = self._ready_flock("2026-10-28", placed=100)
		newer = self._ready_flock("2026-11-14", placed=500)
		result = allocate_sales_to_ready_flocks_for_type(flock_type="Broiler", qty=300)
		older.reload()
		newer.reload()
		self.assertEqual(older.birds_sold, 100)
		self.assertEqual(newer.birds_sold, 200)
		self.assertEqual(result, {"allocated": 300, "unallocated": 0})
		self.assertEqual(older.status, "Ready")
		self.assertEqual(newer.status, "Ready")
