frappe.pages['batch-dashboard'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Batch Dashboard',
		single_column: true
	});
}
