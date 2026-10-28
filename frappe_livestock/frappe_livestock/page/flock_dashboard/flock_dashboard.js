frappe.pages['flock-dashboard'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Flock Dashboard',
		single_column: true
	});
}
