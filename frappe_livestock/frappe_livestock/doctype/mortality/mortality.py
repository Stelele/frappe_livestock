import frappe
from frappe.model.document import Document


class Mortality(Document):
	def validate(self):
		if (self.qty or 0) < 1:
			frappe.throw("Qty must be at least 1", frappe.exceptions.ValidationError)
