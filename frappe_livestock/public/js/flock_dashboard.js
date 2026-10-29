// Flock Dashboard logic, loaded on the flock-dashboard page via the `page_js`
// hook (see hooks.py). Page scripts and `page_js` files are concatenated into
// one page script with the hook file appended last, so this definition is the
// on_page_load handler that sticks; the page-folder file stays a minimal shell.
//
// The flock picker is a body-mounted FieldGroup (NOT page.add_field): in v16
// the page-form area add_field targets is not rendered on this layout, which
// left the dashboard with no visible selector.
frappe.pages["flock-dashboard"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Flock Dashboard"),
		single_column: true,
	});

	var $picker = $('<div class="flock-picker"></div>').appendTo(page.body);
	var $summary = $('<div class="flock-summary"></div>').appendTo(page.body);

	var picker = new frappe.ui.FieldGroup({
		parent: $picker.get(0),
		fields: [
			{
				fieldname: "flock",
				label: __("Flock"),
				fieldtype: "Link",
				options: "Flock",
				onchange: function () {
					render_summary(picker.get_value("flock"));
				},
			},
		],
	});
	picker.make();
	// expose for tests / programmatic use
	wrapper.page.flock_picker = picker;

	function render_summary(name) {
		if (!name) {
			$summary.empty();
			return;
		}
		frappe.call("frappe_livestock.api.flock.get_flock_summary", { flock: name }).then((r) => {
			var s = r.message || {};
			var rows = [
				[__("Livestock Type"), s.livestock_type],
				[__("Start Date"), s.start_date],
				[__("Age (days)"), s.age_days],
				[__("Stage"), s.stage],
				[__("Expected Ready Date"), s.expected_ready_date],
				[__("Quantity Placed"), s.quantity_placed],
				[__("Mortalities"), s.mortalities_total],
				[__("Surviving Birds"), s.surviving_birds],
				[__("Remaining Birds"), s.remaining_birds],
				[__("Birds Sold"), s.birds_sold],
				[__("Total Cost"), s.total_cost],
				[__("Cost per Bird"), s.cost_per_bird],
				[__("Status"), s.status],
			]
				.map(
					(row) =>
						`<tr><td>${frappe.utils.escape_html(row[0] || "")}</td><td>${frappe.utils.escape_html(
							String(row[1] == null ? "" : row[1])
						)}</td></tr>`
				)
				.join("");
			$summary.html(`<table class="table table-bordered"><tbody>${rows}</tbody></table>`);
		});
	}

	// Default to the most-recent non-closed flock. When there is no active
	// flock, stay empty and let the human pick manually (no alert).
	frappe.call("frappe_livestock.api.allocation.get_active_flocks").then((r) => {
		var flocks = r.message || [];
		if (!flocks.length) {
			return;
		}
		picker.set_value("flock", flocks[0].name);
	});
};
