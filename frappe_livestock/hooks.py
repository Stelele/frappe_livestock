app_name = "frappe_livestock"
app_title = "Frappe Livestock"
app_publisher = "Gift Mugweni"
app_description = "A simple module to make managing livestock easier"
app_email = "giftmugweni@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "frappe_livestock",
# 		"logo": "/assets/frappe_livestock/logo.png",
# 		"title": "Frappe Livestock",
# 		"route": "/frappe_livestock",
# 		"has_permission": "frappe_livestock.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/frappe_livestock/css/frappe_livestock.css"
# app_include_js = "/assets/frappe_livestock/js/frappe_livestock.js"

# include js, css files in header of web template
# web_include_css = "/assets/frappe_livestock/css/frappe_livestock.css"
# web_include_js = "/assets/frappe_livestock/js/frappe_livestock.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "frappe_livestock/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
page_js = {"flock-dashboard": "public/js/flock_dashboard.js"}

# include js in doctype views
doctype_js = {
	"Mortality": "public/js/mortality.js",
	"Feed Event": "public/js/feed_event.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "frappe_livestock/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "frappe_livestock.utils.jinja_methods",
# 	"filters": "frappe_livestock.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "frappe_livestock.install.before_install"
# after_install = "frappe_livestock.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "frappe_livestock.uninstall.before_uninstall"
# after_uninstall = "frappe_livestock.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "frappe_livestock.utils.before_app_install"
# after_app_install = "frappe_livestock.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "frappe_livestock.utils.before_app_uninstall"
# after_app_uninstall = "frappe_livestock.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "frappe_livestock.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "frappe_livestock.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Sales Invoice": {
		"on_submit": "frappe_livestock.api.sales.allocate_sales_to_ready_flocks",
	},
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"frappe_livestock.tasks.all"
# 	],
# 	"daily": [
# 		"frappe_livestock.tasks.daily"
# 	],
# 	"hourly": [
# 		"frappe_livestock.tasks.hourly"
# 	],
# 	"weekly": [
# 		"frappe_livestock.tasks.weekly"
# 	],
# 	"monthly": [
# 		"frappe_livestock.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "frappe_livestock.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "frappe_livestock.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "frappe_livestock.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "frappe_livestock.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["frappe_livestock.utils.before_request"]
# after_request = ["frappe_livestock.utils.after_request"]

# Job Events
# ----------
# before_job = ["frappe_livestock.utils.before_job"]
# after_job = ["frappe_livestock.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"frappe_livestock.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
