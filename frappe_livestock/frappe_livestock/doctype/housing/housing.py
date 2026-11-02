import frappe
from frappe.model.document import Document


class Housing(Document):
	def mark_occupied(self, date=None):
		self.status = "Occupied"
		self.last_used_date = date or frappe.utils.today()
		self.save()

	def mark_released(self, date=None, cleaned=False):
		self.status = "Ready"
		if cleaned:
			self.last_cleaned_date = date or frappe.utils.today()
		self.save()
