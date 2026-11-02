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

	def validate(self):
		# capture the saved value before this write, so on_update can tell
		# whether the stocking purchase link actually changed
		self._stocking_pi_before = frappe.db.get_value(self.doctype, self.name, "stocking_purchase_invoice")
		# `sold` is maintained automatically by the sales allocation hook
		# (which writes via frappe.db.set_value, bypassing validate);
		# any hand edit through insert/save is rejected.
		old_sold = frappe.db.get_value(self.doctype, self.name, "sold")
		if int(self.sold or 0) != int(old_sold or 0):
			frappe.throw("Sold is maintained automatically and cannot be edited manually.")

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
