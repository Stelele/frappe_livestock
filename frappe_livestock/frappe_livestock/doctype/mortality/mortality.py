import frappe
from frappe.model.document import Document


class Mortality(Document):
	def validate(self):
		if (self.qty or 0) < 1:
			frappe.throw("Qty must be at least 1", frappe.exceptions.ValidationError)
		if self.batch:
			# serialize concurrent inserts on the batch row so the cumulative
			# ceiling cannot be exceeded by racing requests
			frappe.db.get_value("Livestock Batch", self.batch, "name", for_update=True)
			try:
				batch = frappe.get_doc("Livestock Batch", self.batch)
			except frappe.DoesNotExistError:
				# bad batch link — leave that to Link validation, but log so the
				# missing age/stage stamp is traceable
				frappe.logger("livestock").warning(
					f"Mortality {self.name or 'new'} references missing batch {self.batch}; age/stage not stamped"
				)
				return
			placed = int(batch.quantity_placed or 0)
			if self.name:
				existing = int(
					frappe.db.sql(
						"select sum(qty) from `tabMortality` where batch = %s and name != %s",
						(self.batch, self.name),
					)[0][0]
					or 0
				)
			else:
				existing = int(
					frappe.db.sql(
						"select sum(qty) from `tabMortality` where batch = %s",
						self.batch,
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
