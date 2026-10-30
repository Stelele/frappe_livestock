// Batch Dashboard logic, loaded on the batch-dashboard page via the `page_js`
// hook (see hooks.py). Page scripts and `page_js` files are concatenated into
// one page script with the hook file appended last, so this definition is the
// on_page_load handler that sticks; the page-folder file stays a minimal shell.
//
// The batch picker is a body-mounted FieldGroup (NOT page.add_field): in v16
// the page-form area add_field targets is not rendered on this layout, which
// left the dashboard with no visible selector.
frappe.pages["batch-dashboard"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Batch Dashboard"),
		single_column: true,
	});

	var $picker = $('<div class="batch-picker"></div>').appendTo(page.body);
	var $summary = $('<div class="batch-summary"></div>').appendTo(page.body);

	var picker = new frappe.ui.FieldGroup({
		parent: $picker.get(0),
		fields: [
			{
				fieldname: "batch",
				label: __("Livestock Batch"),
				fieldtype: "Link",
				options: "Livestock Batch",
				onchange: function () {
					render_summary(picker.get_value("batch"));
				},
			},
		],
	});
	picker.make();
	// expose for tests / programmatic use
	wrapper.page.batch_picker = picker;

	function render_summary(name) {
		if (!name) {
			$summary.empty();
			return;
		}
		frappe.call("frappe_livestock.api.batch.get_batch_summary", { batch: name }).then((r) => {
			var s = r.message || {};
			var rows = [
				[__("Livestock Type"), s.livestock_type],
				[__("Start Date"), s.start_date],
				[__("Age (days)"), s.age_days],
				[__("Stage"), s.stage],
				[__("Expected Ready Date"), s.expected_ready_date],
				[__("Quantity Placed"), s.quantity_placed],
				[__("Mortalities"), s.mortalities_total],
				[__("Surviving Birds"), s.surviving],
				[__("Remaining Birds"), s.remaining],
				[__("Birds Sold"), s.sold],
				[__("Total Cost"), s.total_cost],
				[__("Cost per Bird"), s.cost_per_head],
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

	// Default to the most-recent non-closed batch. When there is no active
	// batch, stay empty and let the human pick manually (no alert).
	frappe.call("frappe_livestock.api.allocation.get_active_batches").then((r) => {
		var batches = r.message || [];
		if (!batches.length) {
			return;
		}
		picker.set_value("batch", batches[0].name);
	});
};
