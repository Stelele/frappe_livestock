import frappe


@frappe.whitelist()
def get_batch_summary(batch):
	"""Return one dict with every computed Livestock Batch field for dashboards and reports.

	Pure delegation and shaping layer: all numbers come from the
	Livestock Batch controller methods, assembled here under stable keys.
	"""
	frappe.only_for(("System Manager", "Livestock Dashboard", "Livestock Manager"))
	doc = frappe.get_doc("Livestock Batch", batch)
	return {
		"name": doc.name,
		"livestock_type": doc.livestock_type,
		"start_date": doc.start_date,
		"age_days": doc.age_days(),
		"stage": doc.stage_name(),
		"expected_ready_date": doc.expected_ready_date(),
		"quantity_placed": doc.quantity_placed,
		"mortalities_total": doc.mortalities_total(),
		"surviving": doc.surviving(),
		"remaining": doc.remaining(),
		"sold": doc.sold,
		"total_cost": doc.total_cost(),
		"cost_per_head": doc.cost_per_head(),
		"status": doc.status,
	}
