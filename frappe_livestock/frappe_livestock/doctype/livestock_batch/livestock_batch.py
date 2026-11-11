import frappe
from frappe.model.document import Document
from frappe.utils import add_days, getdate, today

from frappe_livestock.frappe_livestock.doctype.livestock_type.livestock_type import get_stage_for_age


class LivestockBatch(Document):
	def autoname(self):
		base = f"{self.livestock_type} {self.start_date}"
		name = base
		suffix = 2
		while frappe.db.exists(self.doctype, name):
			name = f"{base} {suffix}"
			suffix += 1
		self.name = name

	def insert(self, *args, **kwargs):
		try:
			return super().insert(*args, **kwargs)
		except frappe.DuplicateEntryError:
			# lost the autoname race against a concurrent insert of the same
			# type/start_date — re-run autoname for the next suffix and retry once
			self.name = None
			self.autoname()
			return super().insert(*args, **kwargs)

	def validate(self):
		# capture the saved values before this write, so on_update can tell
		# whether the stocking purchase link / housing actually changed
		self._stocking_pi_before = frappe.db.get_value(self.doctype, self.name, "stocking_purchase_invoice")
		self._housing_before = frappe.db.get_value(self.doctype, self.name, "housing")
		# `sold` is maintained automatically by the sales allocation hook
		# (which writes via frappe.db.set_value, bypassing validate).
		# A save of a document loaded before a concurrent sale would carry a
		# stale in-memory `sold` and be wrongly rejected, so the DB value is
		# authoritative: adopt it instead of throwing.
		old_sold = frappe.db.get_value(self.doctype, self.name, "sold")
		if not self.is_new() and int(self.sold or 0) != int(old_sold or 0):
			self.sold = int(old_sold or 0)

	def on_update(self):
		# when the stocking purchase link is set (and changed), allocate that
		# invoice's stocking lines here as the batch's initial cost — same ledger
		# mechanism as feed, idempotent upsert
		if (
			self.stocking_purchase_invoice
			and self.stocking_purchase_invoice != getattr(self, "_stocking_pi_before", None)
		):
			from frappe_livestock.api.stocking import _allocate_to_batch

			_allocate_to_batch(self.name, self.stocking_purchase_invoice)

		# housing movement audit: when housing changed and a new value is set,
		# leave one traceability comment on the batch timeline
		housing_before = getattr(self, "_housing_before", None)
		if self.housing and self.housing != housing_before:
			old = housing_before or "no housing"
			frappe.get_doc(
				{
					"doctype": "Comment",
					"comment_type": "Comment",
					"reference_doctype": "Livestock Batch",
					"reference_name": self.name,
					"content": f"Moved from {old} to {self.housing} on {today()}",
				}
			).insert(ignore_permissions=True)

	def age_days(self) -> int:
		return max((getdate(today()) - getdate(self.start_date)).days, 0)

	def stage_name(self) -> str | None:
		stages = frappe.get_doc("Livestock Type", self.livestock_type).stages
		stage = get_stage_for_age(stages, self.age_days())
		return stage["stage_name"] if stage else None

	def expected_ready_date(self):
		stages = frappe.get_doc("Livestock Type", self.livestock_type).stages
		if not stages:
			return None
		last_day = max(stage.end_day if hasattr(stage, "end_day") else stage["end_day"] for stage in stages)
		return add_days(getdate(self.start_date), last_day)

	def mortalities_total(self) -> int:
		return int(
			frappe.db.sql("select sum(qty) from `tabMortality` where batch = %s", self.name)[0][0] or 0
		)

	def latest_weight(self) -> dict | None:
		"""Newest-by-date Livestock Weight row for this batch, else None."""
		row = frappe.db.get_value(
			"Livestock Weight",
			{"batch": self.name},
			["date", "average_weight_kg"],
			order_by="date desc",
			as_dict=True,
		)
		if not row:
			return None
		return {"date": row.date, "average_weight_kg": row.average_weight_kg}

	def surviving(self) -> int:
		return int(self.quantity_placed or 0) - self.mortalities_total()

	def remaining(self) -> int:
		return self.surviving() - int(self.sold or 0)

	def total_cost(self) -> float:
		return float(
			frappe.db.sql("select sum(amount) from `tabBatch Cost Item` where batch = %s", self.name)[0][0]
			or 0
		)

	def cost_per_head(self) -> float:
		surviving = self.surviving()
		if surviving == 0:
			return 0.0
		return self.total_cost() / surviving
