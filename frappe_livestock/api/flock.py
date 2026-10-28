import frappe


@frappe.whitelist()
def get_flock_summary(flock):
	"""Return one dict with every computed Flock field for dashboards and reports.

	Pure delegation and shaping layer: all numbers come from the
	Flock controller methods, assembled here under stable keys.
	"""
	doc = frappe.get_doc("Flock", flock)
	return {
		"name": doc.name,
		"livestock_type": doc.livestock_type,
		"start_date": doc.start_date,
		"age_days": doc.age_days(),
		"stage": doc.stage_name(),
		"expected_ready_date": doc.expected_ready_date(),
		"quantity_placed": doc.quantity_placed,
		"mortalities_total": doc.mortalities_total(),
		"surviving_birds": doc.surviving_birds(),
		"remaining_birds": doc.remaining_birds(),
		"birds_sold": doc.birds_sold,
		"total_cost": doc.total_cost(),
		"cost_per_bird": doc.cost_per_bird(),
		"status": doc.status,
	}
