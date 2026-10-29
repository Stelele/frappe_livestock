import frappe
from frappe.model.document import Document
from frappe.utils import add_days, getdate, today

from frappe_livestock.frappe_livestock.doctype.livestock_type.livestock_type import get_stage_for_age


class Flock(Document):
	def autoname(self):
		self.name = f"{self.livestock_type} {self.start_date}"

	def validate(self):
		# capture the saved value before this write, so on_update can tell
		# whether the chick purchase link actually changed
		self._chick_pi_before = frappe.db.get_value(self.doctype, self.name, "chick_purchase_invoice")

	def on_update(self):
		# when the chick purchase link is set (and changed), allocate that
		# invoice's chick lines here as the flock's initial cost — same ledger
		# mechanism as feed, idempotent upsert
		if (
			self.chick_purchase_invoice
			and self.chick_purchase_invoice != getattr(self, "_chick_pi_before", None)
		):
			from frappe_livestock.api.chicks import _allocate_to_flock

			_allocate_to_flock(self.name, self.chick_purchase_invoice)

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
			frappe.db.sql("select sum(qty) from `tabMortality` where flock = %s", self.name)[0][0] or 0
		)

	def surviving_birds(self) -> int:
		return int(self.quantity_placed or 0) - self.mortalities_total()

	def remaining_birds(self) -> int:
		return self.surviving_birds() - int(self.birds_sold or 0)

	def total_cost(self) -> float:
		return float(
			frappe.db.sql("select sum(amount) from `tabFlock Cost Item` where flock = %s", self.name)[0][0]
			or 0
		)

	def cost_per_bird(self) -> float:
		surviving = self.surviving_birds()
		if surviving == 0:
			return 0.0
		return self.total_cost() / surviving
