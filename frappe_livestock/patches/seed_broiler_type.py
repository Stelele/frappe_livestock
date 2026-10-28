import frappe

BROILER_STAGES = [
	{"stage_name": "Day Old Chick", "start_day": 0, "end_day": 20},
	{"stage_name": "Grower", "start_day": 21, "end_day": 41},
	{"stage_name": "Broiler", "start_day": 42, "end_day": 48},
]


def execute():
	if frappe.db.exists("Livestock Type", "Broiler"):
		return

	frappe.get_doc(
		{
			"doctype": "Livestock Type",
			"livestock_type_name": "Broiler",
			"stages": BROILER_STAGES,
		}
	).insert(ignore_permissions=True)
