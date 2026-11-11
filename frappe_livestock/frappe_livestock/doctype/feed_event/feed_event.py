import frappe
from frappe.model.document import Document


class FeedEvent(Document):
	def validate(self):
		if not (self.qty or 0) > 0:
			frappe.throw(frappe._("Qty must be greater than 0"), frappe.exceptions.ValidationError)
