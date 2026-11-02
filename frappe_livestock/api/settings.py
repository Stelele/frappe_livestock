import frappe


@frappe.whitelist()
def get_purchase_context(company=None):
	"""Pre-flight context for the livestock purchase dialog (Task 11).

	Resolves the company, warehouse, and mode of payment defaults plus a
	list of human-readable warnings shown BEFORE the user types anything.

	Args:
		company: Optional company override. When omitted (None), the user's
			default company is used. Passing company="" explicitly forces
			the no-company warning path (used by tests and by Task 11's
			dialog for staleness checks at click time).
	"""
	if company is None:
		company = frappe.defaults.get_user_default("company") or None

	warnings = []

	settings_mop = frappe.db.get_single_value("Livestock Settings", "mode_of_payment") or None
	settings_wh = frappe.db.get_single_value("Livestock Settings", "default_warehouse") or None

	if not company:
		warnings.append("No company default is set for this user. Please select a company.")
	else:
		if not frappe.db.exists("Company", company):
			warnings.append(f"Company '{company}' does not exist.")
			company = None

	warehouse = None
	if settings_wh and frappe.db.exists("Warehouse", settings_wh):
		warehouse = settings_wh
	elif company:
		leaf = frappe.db.get_list(
			"Warehouse", filters={"company": company, "is_group": 0}, pluck="name"
		)
		if len(leaf) == 1:
			warehouse = leaf[0]

	mode_of_payment = None
	if settings_mop and frappe.db.exists("Mode of Payment", settings_mop):
		mode_of_payment = settings_mop
	else:
		if settings_mop:
			warnings.append(
				f"Mode of Payment '{settings_mop}' is configured in Livestock Settings but does not exist."
			)
		elif not frappe.db.exists("Mode of Payment", "Cash"):
			warnings.append(
				'No valid Mode of Payment configured in Livestock Settings and "Cash" does not exist. Please create one.'
			)
		else:
			warnings.append(
				"No valid Mode of Payment configured in Livestock Settings. Please set one."
			)

	if company:
		if not frappe.db.get_value("Company", company, "default_cash_account"):
			warnings.append(
				f"No default cash account set on company '{company}' used by payment."
			)
		if not frappe.db.get_value("Company", company, "default_payable_account"):
			warnings.append(
				f"No default payable account set on company '{company}'."
			)

	return {
		"company": company,
		"warehouse": warehouse,
		"mode_of_payment": mode_of_payment,
		"warnings": warnings,
	}
