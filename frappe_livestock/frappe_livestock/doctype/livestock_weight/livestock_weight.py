import frappe
from frappe.model.document import Document


class LivestockWeight(Document):
	def validate(self):
		if not (self.average_weight_kg or 0) > 0:
			frappe.throw(frappe._("Avg Weight (kg) must be greater than 0"))
		if (self.sample_size or 0) < 0:
			frappe.throw(frappe._("Heads Weighed cannot be negative"))
