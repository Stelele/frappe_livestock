from typing import ClassVar

import frappe
from frappe.tests import IntegrationTestCase

from frappe_livestock.api.allocation import get_active_flocks, split_purchase_to_flocks
from frappe_livestock.api.purchase import create_full_purchase
from frappe_livestock.frappe_livestock.doctype.livestock_type.test_livestock_type import (
	ensure_broiler_type,
)


def _ensure_feed_item():
	if not frappe.db.exists("Item", "Feed"):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "Feed",
				"item_group": "Products",
				"stock_uom": "Nos",
				"is_stock_item": 1,
			}
		).insert(ignore_if_duplicate=True)


class _AllocationFixture(IntegrationTestCase):
	FIXED_FLOCK_DATES: ClassVar = ["2026-08-01", "2026-09-01", "2026-10-01", "2026-10-28", "2026-11-14"]

	def setUp(self):
		super().setUp()
		ensure_broiler_type()
		_ensure_feed_item()
		self._clear_fixed()

	def _clear_fixed(self):
		# Fixed-name fixtures collide across runs whenever a committing test
		# (create_full_purchase commits) persists them; clear for re-runnability.
		if frappe.db.exists("Flock Cost", "PI-FAKE"):
			frappe.delete_doc("Flock Cost", "PI-FAKE", force=True)
		for date in self.FIXED_FLOCK_DATES:
			name = f"Broiler {date}"
			for parent in frappe.get_all("Flock Cost Item", {"flock": name}, pluck="parent"):
				if frappe.db.exists("Flock Cost", parent):
					frappe.delete_doc("Flock Cost", parent, force=True)
			for mortality in frappe.get_all("Mortality", {"flock": name}, pluck="name"):
				frappe.delete_doc("Mortality", mortality, force=True)
			if frappe.db.exists("Flock", name):
				frappe.delete_doc("Flock", name, force=True)

	def _flock(self, date, placed=500):
		return frappe.get_doc(
			{
				"doctype": "Flock",
				"livestock_type": "Broiler",
				"start_date": date,
				"quantity_placed": placed,
			}
		).insert()


class TestAllocationSplit(_AllocationFixture):
	def test_split_across_two_flocks_and_cost(self):
		a = self._flock("2026-10-28")
		b = self._flock("2026-11-14")
		# cost doc referencing a purchase invoice is hand-built to avoid needing a real PI
		cost = frappe.get_doc(  # noqa: F841 -- kept verbatim per task brief
			{
				"doctype": "Flock Cost",
				"purchase_invoice": "PI-FAKE",
				"items": [
					{"item_code": "Feed", "qty": 8, "amount": 80, "flock": a.name},
					{"item_code": "Feed", "qty": 12, "amount": 120, "flock": b.name},
				],
			}
		).insert()
		self.assertEqual(a.total_cost(), 80.0)
		self.assertEqual(b.total_cost(), 120.0)


class TestAllocationZeroBirds(_AllocationFixture):
	def test_cost_per_bird_zero_when_all_dead(self):
		a = self._flock("2026-10-28")
		frappe.get_doc({"doctype": "Mortality", "flock": a.name, "qty": 500}).insert()
		frappe.get_doc(
			{
				"doctype": "Flock Cost",
				"purchase_invoice": "PI-FAKE",
				"items": [{"item_code": "Feed", "qty": 8, "amount": 80, "flock": a.name}],
			}
		).insert()
		self.assertEqual(a.cost_per_bird(), 0.0)


class TestAllocationDuplicate(_AllocationFixture):
	def test_duplicate_purchase_invoice_is_rejected(self):
		base = {
			"doctype": "Flock Cost",
			"purchase_invoice": "PI-FAKE",
			"items": [{"item_code": "Feed", "qty": 8, "amount": 80, "flock": self._flock("2026-10-28").name}],
		}
		frappe.get_doc(base).insert()
		with self.assertRaises(frappe.exceptions.DuplicateEntryError):
			frappe.get_doc(base).insert()


class TestSplitPurchaseToFlocks(_AllocationFixture):
	def setUp(self):
		super().setUp()
		# create_full_purchase commits, so prior runs may have left deterministic
		# "Broiler 2031-*" flocks behind; clear them (cost docs first) for re-runnability.
		for name in frappe.get_all("Flock", {"name": ["like", "Broiler 2031-%"]}, pluck="name"):
			for parent in frappe.get_all("Flock Cost Item", {"flock": name}, pluck="parent"):
				frappe.delete_doc("Flock Cost", parent, force=True)
			frappe.delete_doc("Flock", name, force=True)

	def _purchase(self, qty=20, rate=10):
		company = frappe.defaults.get_user_default("company")
		if frappe.db.exists("Supplier", "FeedCo"):
			supplier = "FeedCo"
		else:
			supplier = (
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
		warehouse = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")
		return create_full_purchase(
			company, supplier, warehouse, [{"item_code": "Feed", "qty": qty, "rate": rate}]
		)

	def _unique_flock(self, placed=500):
		# create_full_purchase commits, so fixed-name flocks would collide on re-runs;
		# use a counter-derived future date for a unique autoname each call.
		if not hasattr(self, "_flock_seq"):
			self._flock_seq = 0
		self._flock_seq += 1
		n = self._flock_seq
		date = f"2031-{(n - 1) // 28 + 1:02d}-{(n - 1) % 28 + 1:02d}"
		return self._flock(date, placed)

	def test_split_derives_amount_from_invoice_rate(self):
		res = self._purchase(qty=20, rate=10)
		a = self._unique_flock()
		b = self._unique_flock()
		split_purchase_to_flocks(
			res["purchase_invoice"],
			[
				{"item_code": "Feed", "qty": 8, "flock": a.name},
				{"item_code": "Feed", "qty": 12, "flock": b.name},
			],
		)
		self.assertEqual(a.total_cost(), 80.0)
		self.assertEqual(b.total_cost(), 120.0)

	def test_split_upsert_replaces_rows_without_doubling(self):
		res = self._purchase(qty=20, rate=10)
		a = self._unique_flock()
		b = self._unique_flock()
		split_purchase_to_flocks(
			res["purchase_invoice"],
			[
				{"item_code": "Feed", "qty": 8, "flock": a.name},
				{"item_code": "Feed", "qty": 12, "flock": b.name},
			],
		)
		split_purchase_to_flocks(res["purchase_invoice"], [{"item_code": "Feed", "qty": 20, "flock": a.name}])
		costs = frappe.get_all("Flock Cost", {"purchase_invoice": res["purchase_invoice"]})
		self.assertEqual(len(costs), 1)
		doc = frappe.get_doc("Flock Cost", costs[0].name)
		self.assertEqual(len(doc.items), 1)
		self.assertEqual(a.total_cost(), 200.0)
		self.assertEqual(b.total_cost(), 0.0)

	def test_split_throws_for_item_not_on_invoice(self):
		a = self._unique_flock()
		with self.assertRaisesRegex(frappe.exceptions.ValidationError, "is not on Purchase Invoice"):
			split_purchase_to_flocks("PI-FAKE", [{"item_code": "Feed", "qty": 1, "flock": a.name}])

	def test_get_active_flocks_newest_first_excludes_closed(self):
		closed = self._flock("2026-08-01")
		older = self._flock("2026-09-01")
		newer = self._flock("2026-10-01")
		frappe.db.set_value("Flock", closed.name, "status", "Closed")
		flocks = get_active_flocks()
		names = [f["name"] for f in flocks]
		self.assertNotIn(closed.name, names)
		self.assertLess(names.index(newer.name), names.index(older.name))
		self.assertEqual(flocks[names.index(newer.name)]["remaining_birds"], 500)
