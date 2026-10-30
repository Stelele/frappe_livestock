from __future__ import annotations

import frappe

LIVESTOCK_DASHBOARD_ROLE = "Livestock Dashboard"

# Read-only access the dashboard consumers (erpnext-dashboard, holdings app)
# need. Granted via frappe.permissions.add_permission / update_permission_property,
# NOT synced as Custom DocPerm fixtures — a Custom DocPerm REPLACES the whole
# standard permission set for a doctype (frappe.model.meta.set_custom_permissions),
# so fixture-syncing one silently strips System Manager / other-role access.
# add_permission preserves standard perms by copying them into Custom DocPerm first.
REPORTING_PERMISSIONS = {
	# livestock doctypes
	"Flock": {"read": 1},
	"Flock Cost": {"read": 1},
	"Flock Cost Item": {"read": 1},
	"Flock Sale": {"read": 1},
	"Flock Sale Item": {"read": 1},
	"Livestock Type": {"read": 1},
	"Livestock Stage": {"read": 1},
	"Housing": {"read": 1},
	"Housing Region": {"read": 1},
	"Mortality": {"read": 1},
	"Feed Event": {"read": 1},
	# ERPNext core the reporting joins read through
	"Account": {"read": 1},
	"Company": {"read": 1},
	"GL Entry": {"read": 1},
	"Item": {"read": 1},
	"Item Group": {"read": 1},
	"Mode of Payment": {"read": 1},
	"Payment Entry": {"read": 1},
	"Purchase Invoice": {"read": 1},
	"Purchase Order": {"read": 1},
	"Purchase Receipt": {"read": 1},
	"Sales Invoice": {"read": 1},
	"Supplier": {"read": 1},
	"UOM": {"read": 1},
	"Warehouse": {"read": 1},
}


def after_install():
	ensure_reporting_permissions()


def after_migrate():
	"""Keep the dashboard role's permissions in sync on every migrate (idempotent)."""
	ensure_reporting_permissions()


def ensure_reporting_permissions():
	"""Grant REPORTING_PERMISSIONS (read-only) to LIVESTOCK_DASHBOARD_ROLE without
	clobbering other roles' access."""
	from frappe.permissions import add_permission, update_permission_property

	if not frappe.db.exists("Role", LIVESTOCK_DASHBOARD_ROLE):
		frappe.get_doc(
			{"doctype": "Role", "role_name": LIVESTOCK_DASHBOARD_ROLE, "desk_access": 0, "is_custom": 1}
		).insert(ignore_permissions=True)

	for doctype, ptypes in REPORTING_PERMISSIONS.items():
		for ptype in ptypes:
			existing = frappe.db.get_value(
				"Custom DocPerm",
				{"parent": doctype, "role": LIVESTOCK_DASHBOARD_ROLE, "permlevel": 0},
				"name",
			)
			if not existing:
				add_permission(doctype, LIVESTOCK_DASHBOARD_ROLE, ptype=ptype)
				continue
			if not frappe.db.get_value("Custom DocPerm", existing, ptype):
				update_permission_property(doctype, LIVESTOCK_DASHBOARD_ROLE, 0, ptype, 1)

	frappe.db.commit()
