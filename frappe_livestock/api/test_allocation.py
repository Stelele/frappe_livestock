from typing import ClassVar

import frappe
from frappe.tests import IntegrationTestCase

from frappe_livestock.api.allocation import get_active_batches, split_purchase_to_batches
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
	FIXED_BATCH_DATES: ClassVar = ["2026-08-01", "2026-09-01", "2026-10-01", "2026-10-28", "2026-11-14"]

	def setUp(self):
		super().setUp()
		ensure_broiler_type()
		_ensure_feed_item()
		self._clear_fixed()

	def _clear_fixed(self):
		# Fixed-name batches collide across runs whenever a committing test
		# (create_full_purchase commits) persists them; clear for re-runnability.
		for date in self.FIXED_BATCH_DATES:
			name = f"Broiler {date}"
			for parent in frappe.get_all("Batch Cost Item", {"batch": name}, pluck="parent"):
				if frappe.db.exists("Batch Cost", parent):
					frappe.delete_doc("Batch Cost", parent, force=True)
			for mortality in frappe.get_all("Mortality", {"batch": name}, pluck="name"):
				frappe.delete_doc("Mortality", mortality, force=True)
			if frappe.db.exists("Livestock Batch", name):
				frappe.delete_doc("Livestock Batch", name, force=True)

	def _batch(self, date, placed=500):
		return frappe.get_doc(
			{
				"doctype": "Livestock Batch",
				"livestock_type": "Broiler",
				"start_date": date,
				"quantity_placed": placed,
			}
		).insert()

	def _real_pi(self, qty=20, rate=10):
		# Idempotent guards in Task 6 style: distinctive supplier/item reused if present.
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
		)["purchase_invoice"]


class TestAllocationSplit(_AllocationFixture):
	def setUp(self):
		super().setUp()
		self.pi = self._real_pi()

	def test_split_across_two_batches_and_cost(self):
		a = self._batch("2026-10-28")
		b = self._batch("2026-11-14")
		cost = frappe.get_doc(  # noqa: F841 -- kept verbatim per task brief
			{
				"doctype": "Batch Cost",
				"purchase_invoice": self.pi,
				"items": [
					{"item_code": "Feed", "qty": 8, "amount": 80, "batch": a.name},
					{"item_code": "Feed", "qty": 12, "amount": 120, "batch": b.name},
				],
			}
		).insert()
		self.assertEqual(a.total_cost(), 80.0)
		self.assertEqual(b.total_cost(), 120.0)


class TestAllocationZeroBirds(_AllocationFixture):
	def setUp(self):
		super().setUp()
		self.pi = self._real_pi()

	def test_cost_per_head_zero_when_all_dead(self):
		a = self._batch("2026-10-28")
		frappe.get_doc({"doctype": "Mortality", "batch": a.name, "qty": 500}).insert()
		frappe.get_doc(
			{
				"doctype": "Batch Cost",
				"purchase_invoice": self.pi,
				"items": [{"item_code": "Feed", "qty": 8, "amount": 80, "batch": a.name}],
			}
		).insert()
		self.assertEqual(a.cost_per_head(), 0.0)


class TestAllocationDuplicate(_AllocationFixture):
	def setUp(self):
		super().setUp()
		self.pi = self._real_pi()

	def test_duplicate_purchase_invoice_is_rejected(self):
		base = {
			"doctype": "Batch Cost",
			"purchase_invoice": self.pi,
			"items": [{"item_code": "Feed", "qty": 8, "amount": 80, "batch": self._batch("2026-10-28").name}],
		}
		frappe.get_doc(base).insert()
		with self.assertRaises(frappe.exceptions.DuplicateEntryError):
			frappe.get_doc(base).insert()


class TestSplitPurchaseToBatches(_AllocationFixture):
	def setUp(self):
		super().setUp()
		# create_full_purchase commits, so prior runs may have left deterministic
		# "Broiler 2031-*" batches behind; clear them (cost docs first) for re-runnability.
		for name in frappe.get_all("Livestock Batch", {"name": ["like", "Broiler 2031-%"]}, pluck="name"):
			for parent in frappe.get_all("Batch Cost Item", {"batch": name}, pluck="parent"):
				frappe.delete_doc("Batch Cost", parent, force=True)
			frappe.delete_doc("Livestock Batch", name, force=True)

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

	def _unique_batch(self, placed=500):
		# create_full_purchase commits, so fixed-name batches would collide on re-runs;
		# use a counter-derived future date for a unique autoname each call.
		if not hasattr(self, "_batch_seq"):
			self._batch_seq = 0
		self._batch_seq += 1
		n = self._batch_seq
		date = f"2031-{(n - 1) // 28 + 1:02d}-{(n - 1) % 28 + 1:02d}"
		return self._batch(date, placed)

	def test_split_derives_amount_from_invoice_rate(self):
		res = self._purchase(qty=20, rate=10)
		a = self._unique_batch()
		b = self._unique_batch()
		split_purchase_to_batches(
			res["purchase_invoice"],
			[
				{"item_code": "Feed", "qty": 8, "batch": a.name},
				{"item_code": "Feed", "qty": 12, "batch": b.name},
			],
		)
		self.assertEqual(a.total_cost(), 80.0)
		self.assertEqual(b.total_cost(), 120.0)

	def test_split_upsert_replaces_rows_without_doubling(self):
		res = self._purchase(qty=20, rate=10)
		a = self._unique_batch()
		b = self._unique_batch()
		split_purchase_to_batches(
			res["purchase_invoice"],
			[
				{"item_code": "Feed", "qty": 8, "batch": a.name},
				{"item_code": "Feed", "qty": 12, "batch": b.name},
			],
		)
		split_purchase_to_batches(
			res["purchase_invoice"], [{"item_code": "Feed", "qty": 20, "batch": a.name}], force=1
		)
		costs = frappe.get_all("Batch Cost", {"purchase_invoice": res["purchase_invoice"]})
		self.assertEqual(len(costs), 1)
		doc = frappe.get_doc("Batch Cost", costs[0].name)
		self.assertEqual(len(doc.items), 1)
		self.assertEqual(a.total_cost(), 200.0)

	def test_split_idempotent_with_nonterminating_rate(self):
		# rate 1.2 x qty 3 = 3.5999999999999996 in float vs 3.6 rounded in DB:
		# identical re-runs must stay silent (no throw, no new Comment).
		res = self._purchase(qty=6, rate=1.2)
		pi = res["purchase_invoice"]
		a = self._unique_batch()
		b = self._unique_batch()
		rows = [
			{"item_code": "Feed", "qty": 3, "batch": a.name},
			{"item_code": "Feed", "qty": 3, "batch": b.name},
		]
		split_purchase_to_batches(pi, rows)
		costs = frappe.get_all("Batch Cost", {"purchase_invoice": pi})
		self.assertEqual(len(costs), 1)
		before = frappe.get_all(
			"Comment", {"reference_doctype": "Batch Cost", "reference_name": costs[0].name}
		)
		# genuinely identical re-run: must NOT throw "Confirm overwrite"
		split_purchase_to_batches(pi, rows)
		after = frappe.get_all(
			"Comment", {"reference_doctype": "Batch Cost", "reference_name": costs[0].name}
		)
		self.assertEqual(len(after) - len(before), 0)
		costs = frappe.get_all("Batch Cost", {"purchase_invoice": pi})
		self.assertEqual(len(costs), 1)

	def test_split_reordered_rows_are_idempotent(self):
		res = self._purchase(qty=20, rate=10)
		pi = res["purchase_invoice"]
		a = self._unique_batch()
		b = self._unique_batch()
		split_purchase_to_batches(
			pi,
			[
				{"item_code": "Feed", "qty": 8, "batch": a.name},
				{"item_code": "Feed", "qty": 12, "batch": b.name},
			],
		)
		costs = frappe.get_all("Batch Cost", {"purchase_invoice": pi})
		self.assertEqual(len(costs), 1)
		before = frappe.get_all(
			"Comment", {"reference_doctype": "Batch Cost", "reference_name": costs[0].name}
		)
		# same rows in different order: silent idempotent, no throw, no Comment
		split_purchase_to_batches(
			pi,
			[
				{"item_code": "Feed", "qty": 12, "batch": b.name},
				{"item_code": "Feed", "qty": 8, "batch": a.name},
			],
		)
		after = frappe.get_all(
			"Comment", {"reference_doctype": "Batch Cost", "reference_name": costs[0].name}
		)
		self.assertEqual(len(after) - len(before), 0)
		costs = frappe.get_all("Batch Cost", {"purchase_invoice": pi})
		self.assertEqual(len(costs), 1)

	def test_split_malformed_force_string_throws(self):
		res = self._purchase(qty=20, rate=10)
		pi = res["purchase_invoice"]
		a = self._unique_batch()
		with self.assertRaisesRegex(frappe.exceptions.ValidationError, "force must be a boolean"):
			split_purchase_to_batches(
				pi, [{"item_code": "Feed", "qty": 20, "batch": a.name}], force="{not-json"
			)
		self.assertEqual(b.total_cost(), 0.0)

	def test_split_throws_for_item_not_on_invoice(self):
		a = self._unique_batch()
		with self.assertRaisesRegex(frappe.exceptions.ValidationError, "is not on Purchase Invoice"):
			split_purchase_to_batches("PI-FAKE", [{"item_code": "Feed", "qty": 1, "batch": a.name}])

	def test_get_active_batches_newest_first_excludes_closed(self):
		closed = self._batch("2026-08-01")
		older = self._batch("2026-09-01")
		newer = self._batch("2026-10-01")
		frappe.db.set_value("Livestock Batch", closed.name, "status", "Closed")
		batches = get_active_batches()
		names = [f["name"] for f in batches]
		self.assertNotIn(closed.name, names)
		self.assertLess(names.index(newer.name), names.index(older.name))
		self.assertEqual(batches[names.index(newer.name)]["remaining"], 500)

	def test_split_rejects_closed_batch(self):
		res = self._purchase(qty=20, rate=10)
		a = self._unique_batch()
		frappe.db.set_value("Livestock Batch", a.name, "status", "Closed")
		with self.assertRaisesRegex(frappe.exceptions.ValidationError, "is closed"):
			split_purchase_to_batches(
				res["purchase_invoice"], [{"item_code": "Feed", "qty": 5, "batch": a.name}]
			)

	def test_split_requires_force_for_conflicting_overwrite(self):
		res = self._purchase(qty=20, rate=10)
		pi = res["purchase_invoice"]
		a = self._unique_batch()
		b = self._unique_batch()
		first = [
			{"item_code": "Feed", "qty": 8, "batch": a.name},
			{"item_code": "Feed", "qty": 12, "batch": b.name},
		]
		split_purchase_to_batches(pi, first)
		# same rows upsert silently (idempotent) with NO new Comment
		costs = frappe.get_all("Batch Cost", {"purchase_invoice": pi})
		self.assertEqual(len(costs), 1)
		idle_before = frappe.get_all(
			"Comment", {"reference_doctype": "Batch Cost", "reference_name": costs[0].name}
		)
		split_purchase_to_batches(pi, first)
		idle_after = frappe.get_all(
			"Comment", {"reference_doctype": "Batch Cost", "reference_name": costs[0].name}
		)
		self.assertEqual(len(idle_after) - len(idle_before), 0)
		costs = frappe.get_all("Batch Cost", {"purchase_invoice": pi})
		self.assertEqual(len(costs), 1)
		# different rows without force are rejected
		with self.assertRaisesRegex(frappe.exceptions.ValidationError, "Confirm overwrite"):
			split_purchase_to_batches(pi, [{"item_code": "Feed", "qty": 20, "batch": a.name}])
		# different rows with force overwrite and leave exactly one new Comment
		before = frappe.get_all(
			"Comment", {"reference_doctype": "Batch Cost", "reference_name": costs[0].name}
		)
		split_purchase_to_batches(pi, [{"item_code": "Feed", "qty": 20, "batch": a.name}], force=1)
		after = frappe.get_all(
			"Comment", {"reference_doctype": "Batch Cost", "reference_name": costs[0].name}
		)
		self.assertEqual(len(after) - len(before), 1)
		doc = frappe.get_doc("Batch Cost", costs[0].name)
		self.assertEqual(len(doc.items), 1)
		self.assertEqual(a.total_cost(), 200.0)

	def test_split_idempotent_with_nonterminating_rate(self):
		# rate 1.2 x qty 3 = 3.5999999999999996 in float vs 3.6 rounded in DB:
		# identical re-runs must stay silent (no throw, no new Comment).
		res = self._purchase(qty=6, rate=1.2)
		pi = res["purchase_invoice"]
		a = self._unique_batch()
		b = self._unique_batch()
		rows = [
			{"item_code": "Feed", "qty": 3, "batch": a.name},
			{"item_code": "Feed", "qty": 3, "batch": b.name},
		]
		split_purchase_to_batches(pi, rows)
		costs = frappe.get_all("Batch Cost", {"purchase_invoice": pi})
		self.assertEqual(len(costs), 1)
		before = frappe.get_all(
			"Comment", {"reference_doctype": "Batch Cost", "reference_name": costs[0].name}
		)
		# genuinely identical re-run: must NOT throw "Confirm overwrite"
		split_purchase_to_batches(pi, rows)
		after = frappe.get_all(
			"Comment", {"reference_doctype": "Batch Cost", "reference_name": costs[0].name}
		)
		self.assertEqual(len(after) - len(before), 0)
		costs = frappe.get_all("Batch Cost", {"purchase_invoice": pi})
		self.assertEqual(len(costs), 1)

	def test_split_reordered_rows_are_idempotent(self):
		res = self._purchase(qty=20, rate=10)
		pi = res["purchase_invoice"]
		a = self._unique_batch()
		b = self._unique_batch()
		split_purchase_to_batches(
			pi,
			[
				{"item_code": "Feed", "qty": 8, "batch": a.name},
				{"item_code": "Feed", "qty": 12, "batch": b.name},
			],
		)
		costs = frappe.get_all("Batch Cost", {"purchase_invoice": pi})
		self.assertEqual(len(costs), 1)
		before = frappe.get_all(
			"Comment", {"reference_doctype": "Batch Cost", "reference_name": costs[0].name}
		)
		# same rows in different order: silent idempotent, no throw, no Comment
		split_purchase_to_batches(
			pi,
			[
				{"item_code": "Feed", "qty": 12, "batch": b.name},
				{"item_code": "Feed", "qty": 8, "batch": a.name},
			],
		)
		after = frappe.get_all(
			"Comment", {"reference_doctype": "Batch Cost", "reference_name": costs[0].name}
		)
		self.assertEqual(len(after) - len(before), 0)
		costs = frappe.get_all("Batch Cost", {"purchase_invoice": pi})
		self.assertEqual(len(costs), 1)

	def test_split_malformed_force_string_throws(self):
		res = self._purchase(qty=20, rate=10)
		pi = res["purchase_invoice"]
		a = self._unique_batch()
		with self.assertRaisesRegex(frappe.exceptions.ValidationError, "force must be a boolean"):
			split_purchase_to_batches(
				pi, [{"item_code": "Feed", "qty": 20, "batch": a.name}], force="{not-json"
			)
