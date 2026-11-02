import frappe
from frappe.model.document import Document


class Mortality(Document):
	def validate(self):
		if (self.qty or 0) < 1:
			frappe.throw("Qty must be at least 1", frappe.exceptions.ValidationError)
		if self.batch:
			try:
				batch = frappe.get_doc("Livestock Batch", self.batch)
			except frappe.DoesNotExistError:
				# bad batch link — leave that to Link validation
				return
			placed = int(batch.quantity_placed or 0)
			args = [self.batch]
			not_self = ""
			if self.name:
				not_self = " and name != %s"
				args.append(self.name)
			existing = int(
				frappe.db.sql(
					f"select sum(qty) from `tabMortality` where batch = %s{not_self}",
					tuple(args),
				)[0][0]
				or 0
			)
			if existing + int(self.qty or 0) > placed:
				frappe.throw(
					f"Deaths cannot exceed the {placed} birds placed on batch {self.batch}",
					frappe.exceptions.ValidationError,
				)
			if self.is_new():
				self.age_days = batch.age_days()
				self.stage = batch.stage_name()
