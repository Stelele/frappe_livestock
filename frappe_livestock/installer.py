from __future__ import annotations

import frappe

LIVESTOCK_DASHBOARD_ROLE = "Livestock Dashboard"
LIVESTOCK_MANAGER_ROLE = "Livestock Manager"
LIVESTOCK_OPERATOR_ROLE = "Livestock Operator"

# Read-only access the dashboard consumers (erpnext-dashboard, holdings app)
# need. Granted via frappe.permissions.add_permission / update_permission_property,
# NOT synced as Custom DocPerm fixtures — a Custom DocPerm REPLACES the whole
# standard permission set for a doctype (frappe.model.meta.set_custom_permissions),
# so fixture-syncing one silently strips System Manager / other-role access.
# add_permission preserves standard perms by copying them into Custom DocPerm first.
REPORTING_PERMISSIONS = {
	# livestock doctypes
	"Livestock Batch": {"read": 1},
	"Batch Cost": {"read": 1},
	"Batch Cost Item": {"read": 1},
	"Batch Sale": {"read": 1},
	"Batch Sale Item": {"read": 1},
	"Livestock Type": {"read": 1},
	"Livestock Stage": {"read": 1},
	"Housing": {"read": 1},
	"Housing Region": {"read": 1},
	"Mortality": {"read": 1},
	"Feed Event": {"read": 1},
	"Livestock Weight": {"read": 1},
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
	ensure_livestock_roles()


def before_install():
	"""Refuse to install on any Frappe major this app does not target.

	Everything here is built and tested against Frappe/ERPNext v16
	(16.54.0 / 16.52.1 at time of writing); v17 changes are already
	generating deprecation warnings in tested code paths.
	"""
	major = int(frappe.__version__.split(".")[0])
	if major != 16:
		frappe.throw(
			frappe._(
				"frappe_livestock supports Frappe v16 only. This site runs Frappe {0}. Install on a v16 bench."
			).format(frappe.__version__)
		)


def after_migrate():
	"""Keep the dashboard consumers' (Dashboard + Manager) permissions in sync on every migrate (idempotent)."""
	ensure_reporting_permissions()
	ensure_livestock_roles()


def ensure_reporting_permissions():
	"""Grant REPORTING_PERMISSIONS (read-only) to the dashboard consumers
	without clobbering other roles' access.

	RULING (controller, round-1 review): "Livestock Manager" is the app's
	power role and receives the same ERPNext read surface the Livestock
	Dashboard role already has — reporting endpoints join ERPNext core
	doctypes (Item, plus the ledgers in REPORTING_PERMISSIONS), so Manager
	gets the full read set too.
	"""
	from frappe.permissions import add_permission, update_permission_property

	for role, desk in ((LIVESTOCK_DASHBOARD_ROLE, 0), (LIVESTOCK_MANAGER_ROLE, 1)):
		if not frappe.db.exists("Role", role):
			frappe.get_doc(
				{"doctype": "Role", "role_name": role, "desk_access": desk, "is_custom": 1}
			).insert(ignore_permissions=True)

	for role in (LIVESTOCK_DASHBOARD_ROLE, LIVESTOCK_MANAGER_ROLE):
		for doctype, ptypes in REPORTING_PERMISSIONS.items():
			for ptype in ptypes:
				existing = frappe.db.get_value(
					"Custom DocPerm",
					{"parent": doctype, "role": role, "permlevel": 0},
					"name",
				)
				if not existing:
					add_permission(doctype, role, ptype=ptype)
					continue
				if not frappe.db.get_value("Custom DocPerm", existing, ptype):
					update_permission_property(doctype, role, 0, ptype, 1)

	frappe.db.commit()


def ensure_livestock_roles():
	"""Create the Livestock Manager and Livestock Operator roles if missing,
	and grant their permission booleans (idempotent).

	Mirrors the permissions arrays in each doctype's JSON. The booleans must
	be written here via add_permission / update_permission_property — not
	just in JSON — because every livestock doctype already carries Custom
	DocPerm rows (for the Livestock Dashboard role), and once any Custom
	DocPerm exists Frappe's Meta.set_custom_permissions ignores the JSON
	standard perms at runtime. Nothing is fixture-synced as Custom DocPerm.
	"""
	from frappe.permissions import add_permission, update_permission_property

	for role in (LIVESTOCK_MANAGER_ROLE, LIVESTOCK_OPERATOR_ROLE):
		if not frappe.db.exists("Role", role):
			frappe.get_doc(
				{"doctype": "Role", "role_name": role, "desk_access": 1, "is_custom": 1}
			).insert(ignore_permissions=True)

	full = ("create", "delete", "email", "export", "print", "read", "report", "share", "write")
	for doctype in (
		"Livestock Type",
		"Livestock Batch",
		"Feed Event",
		"Mortality",
		"Livestock Weight",
		"Batch Cost",
		"Batch Sale",
		"Housing",
	):
		_ensure_role_ptypes(doctype, LIVESTOCK_MANAGER_ROLE, full, add_permission, update_permission_property)
	for doctype in ("Livestock Stage", "Housing Region", "Batch Cost Item", "Batch Sale Item"):
		_ensure_role_ptypes(doctype, LIVESTOCK_MANAGER_ROLE, ("read",), add_permission, update_permission_property)
	for doctype in ("Feed Event", "Mortality", "Livestock Weight"):
		_ensure_role_ptypes(
			doctype, LIVESTOCK_OPERATOR_ROLE, ("create", "read", "report", "write"), add_permission, update_permission_property
		)
	for doctype in ("Livestock Batch", "Livestock Type", "Housing"):
		_ensure_role_ptypes(doctype, LIVESTOCK_OPERATOR_ROLE, ("read",), add_permission, update_permission_property)

	frappe.db.commit()


def _ensure_role_ptypes(doctype, role, ptypes, add_permission, update_permission_property):
	"""Grant one role's ptypes on one doctype without clobbering other roles."""
	for ptype in ptypes:
		existing = frappe.db.get_value(
			"Custom DocPerm",
			{"parent": doctype, "role": role, "permlevel": 0},
			"name",
		)
		if not existing:
			add_permission(doctype, role, ptype=ptype)
			continue
		if not frappe.db.get_value("Custom DocPerm", existing, ptype):
			update_permission_property(doctype, role, 0, ptype, 1)
