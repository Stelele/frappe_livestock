import frappe
from frappe.model.document import Document


class Housing(Document):
	def validate(self):
		total = sum(row.capacity or 0 for row in self.regions)
		if self.capacity and total > self.capacity:
			frappe.throw(
				frappe._("Sum of region capacities ({0}) exceeds Housing capacity ({1})").format(
					total, self.capacity
				)
			)

	def mark_occupied(self, date=None):
		self.status = "Occupied"
		self.last_used_date = date or frappe.utils.today()
		self.save()

	def mark_released(self, date=None, cleaned=False):
		self.status = "Ready"
		if cleaned:
			self.last_cleaned_date = date or frappe.utils.today()
		self.save()
