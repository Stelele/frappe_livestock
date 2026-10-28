import frappe
from frappe.model.document import Document
from frappe.utils import add_days, getdate, today

from frappe_livestock.frappe_livestock.doctype.livestock_type.livestock_type import get_stage_for_age


class Flock(Document):
	def autoname(self):
		self.name = f"{self.livestock_type} {self.start_date}"

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
