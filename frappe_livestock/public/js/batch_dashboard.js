// Batch Dashboard logic via the `page_js` hook (see hooks.py). This file is the
// SOLE page-load owner; the page-folder shell stays comment-only (as purchase-entry).
frappe.pages["batch-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Batch Dashboard"),
		single_column: true,
	});
	page.body.empty();

	const $picker = $('<div class="batch-picker"></div>').appendTo(page.body);
	const $hint = $('<p class="text-muted">' + __("Pick a Livestock Batch") + "</p>").appendTo(page.body);
	const $row = $('<div class="row"></div>').appendTo(page.body);
	const $left = $('<div class="col-sm-12 col-md-7"></div>').appendTo($row);
	const $right = $('<div class="col-sm-12 col-md-5"></div>').appendTo($row);
	$row.hide();
	let current = null;

	const picker = new frappe.ui.FieldGroup({
		parent: $picker.get(0),
		fields: [
			{
				fieldname: "batch",
				label: __("Livestock Batch"),
				fieldtype: "Link",
				options: "Livestock Batch",
				onchange: function () {
					const name = picker.get_value("batch");
					if (name === current) return;
					if (picker.get_value("batch") !== name) return;
					if (!name) {
						current = null;
						$left.empty();
						$right.empty();
						$row.hide();
						$hint.show();
						return;
					}
					load(name);
				},
			},
		],
	});
	picker.make();

	function esc(v) {
		return frappe.utils.escape_html(String(v === null || v === undefined ? "" : v));
	}

	function dash(v) {
		return v === null || v === undefined || v === "" ? "—" : esc(v);
	}

	function money(x) {
		if (x === null || x === undefined || x === "") return "—";
		const fn = (frappe.utils && frappe.utils.fmt_money) || window.fmt_money;
		if (typeof fn === "function") {
			try {
				return fn(x, 2);
			} catch (e) {
				// fall through to the raw number below
			}
		}
		return String(x);
	}

	function rel(date_str) {
		if (!date_str) return "—";
		try {
			if (frappe.datetime && typeof frappe.datetime.prettyDate === "function") {
				return frappe.datetime.prettyDate(date_str) || String(date_str);
			}
			if (frappe.utils && typeof frappe.utils.pretty_date === "function") {
				return frappe.utils.pretty_date(date_str) || String(date_str);
			}
		} catch (e) {
			// fall through to the raw string below
		}
		return String(date_str);
	}

	function is_stale(date_str) {
		if (!date_str) return false;
		const d = new Date(String(date_str).replace(/-/g, "/"));
		if (isNaN(d.getTime())) return false;
		const now = new Date();
		const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
		const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
		return (today - day) / 86400000 > 1;
	}

	function fresh(date_str, is_active) {
		if (!date_str) return "—";
		let text = esc(rel(date_str)) + " (" + esc(date_str) + ")";
		if (is_active && is_stale(date_str)) text = '<span class="text-danger">' + text + "</span>";
		return text;
	}

	const STATUS_COLORS = { Active: "blue", Ready: "green" };

	function pill(status) {
		const color = STATUS_COLORS[status] || "grey";
		return '<span class="indicator-pill ' + color + '">' + esc(status) + "</span>";
	}

	function detail_row(label, value_html, value_cls) {
		return (
			'<div class="d-flex justify-content-between align-items-baseline">' +
			'<span class="text-muted text-truncate flex-grow-1">' +
			esc(label) +
			'</span><span class="font-weight-bold text-right' +
			(value_cls ? " " + value_cls : "") +
			'">' +
			value_html +
			"</span></div>"
		);
	}

	function load(name) {
		current = name;
		if (!name) {
			$left.empty();
			$right.empty();
			$row.hide();
			$hint.show();
			return;
		}
		$hint.hide();
		$row.show();
		$left.html('<p class="text-muted">' + __("Loading…") + "</p>");
		$right.empty();
		frappe
			.call("frappe_livestock.api.reporting.get_ops_snapshot", { batch: name })
			.then(function (r) {
				if (picker.get_value("batch") !== name) return;
				render(r.message || {});
			})
			.fail(function () {
				if (picker.get_value("batch") !== name) return;
				$left.empty();
				$right.empty();
				$row.hide();
				$hint.show();
				// the server error toast is already shown; the batch may simply
				// be unreadable — show a neutral message, not an access claim
				frappe.msgprint(__("Could not load batch snapshot. Please try again."));
			});
	}

	function render(s) {
		s = s || {};
		const is_active = s.status === "Active";
		const mort = s.mortality_pct === null || s.mortality_pct === undefined ? "—" : (Number(s.mortality_pct) * 100).toFixed(1) + "%";
		const fcr = s.fcr === null || s.fcr === undefined ? "—" : Number(s.fcr).toFixed(2);
		$hint.hide();
		$row.show();

		let left = '<div class="row">';
		left += '<div class="col-sm-6"><div class="frappe-card"><div class="text-muted">' + esc(__("Status")) + "</div><h3>" + pill(s.status) + "</h3></div></div>";
		left += '<div class="col-sm-6"><div class="frappe-card"><div class="text-muted">' + esc(__("Surviving")) + "</div><h3>" + dash(s.surviving) + "</h3></div></div>";
		left += '<div class="col-sm-6"><div class="frappe-card"><div class="text-muted">' + esc(__("Cost per Head")) + "</div><h3>" + esc(money(s.cost_per_head)) + "</h3></div></div>";
		left += '<div class="col-sm-6"><div class="frappe-card"><div class="text-muted">' + esc(__("Mortality")) + "</div><h3>" + esc(mort) + "</h3></div></div>";
		left += "</div>" + '<div class="row">';
		left += '<div class="col-sm-6"><div class="frappe-card"><div class="text-muted">' + esc(__("FCR")) + "</div><h3>" + esc(fcr) + "</h3></div></div>";
		left += "</div>";
		left += "<div>";
		left += '<button class="btn btn-secondary btn-sm" data-action="feed">' + esc(__("Record Feed")) + "</button>";
		left += '<button class="btn btn-secondary btn-sm" data-action="mortality">' + esc(__("Record Mortality")) + "</button>";
		left += '<button class="btn btn-secondary btn-sm" data-action="weigh">' + esc(__("Weigh")) + "</button>";
		left += '<button class="btn btn-secondary btn-sm" data-action="sell">' + esc(__("Sell birds")) + "</button>";
		left += '<button class="btn btn-secondary btn-sm" data-action="open">' + esc(__("Open Batch")) + "</button>";
		left += "</div>";
		$left.html(left);
		$left.find('[data-action="feed"]').on("click", do_feed);
		$left.find('[data-action="mortality"]').on("click", do_mortality);
		$left.find('[data-action="weigh"]').on("click", do_weigh);
		$left.find('[data-action="sell"]').on("click", do_sell);
		$left.find('[data-action="open"]').on("click", do_open);

		let right = '<div class="frappe-card"><div class="text-muted"><small>' + esc(__("Details")) + "</small></div>";
		right += detail_row(__("Type"), dash(s.livestock_type));
		right += detail_row(__("Start Date"), dash(s.start_date));
		right += detail_row(__("Age"), dash(s.age_days));
		right += detail_row(__("Stage"), dash(s.stage));
		right += detail_row(__("Placed"), dash(s.quantity_placed));
		right += detail_row(__("Sold"), dash(s.sold));
		right += detail_row(__("Remaining"), dash(s.remaining));
		right += detail_row(__("Ready"), dash(s.expected_ready_date));
		right += detail_row(
			__("Weight"),
			s.latest_weight_kg === null || s.latest_weight_kg === undefined ? "—" : esc(s.latest_weight_kg) + " (" + esc(s.latest_weight_date) + ")"
		);
		right += detail_row(__("Feed (last)"), fresh(s.last_feed_date, is_active));
		right += detail_row(__("Mortality (last)"), fresh(s.last_mortality_date, is_active));
		right += '<div class="text-muted"><small>' + esc(__("Today & P&L")) + "</small></div>";
		right += detail_row(__("Feed Today"), dash(s.feed_consumed_today));
		right += detail_row(__("Revenue"), esc(money(s.revenue)));
		const profit_cls = s.profit !== null && s.profit !== undefined && Number(s.profit) < 0 ? "text-danger" : "";
		right += detail_row(__("Profit"), esc(money(s.profit)), profit_cls);
		right += "</div>";
		$right.html(right);
	}

	function need_batch() {
		const name = picker.get_value("batch");
		if (!name) frappe.msgprint(__("Select a batch first"));
		return name;
	}

	function quick_capture(doctype, opts) {
		frappe.route_options = opts;
		frappe.new_doc(doctype);
	}

	function do_feed() {
		const name = need_batch();
		if (name) quick_capture("Feed Event", { batch: name });
	}

	function do_mortality() {
		const name = need_batch();
		if (name) quick_capture("Mortality", { batch: name });
	}

	function do_weigh() {
		const name = need_batch();
		if (name) quick_capture("Livestock Weight", { batch: name });
	}

	function do_sell() {
		const name = need_batch();
		if (!name) return;
		frappe.prompt(
			[
				{ label: __("Customer"), fieldname: "customer", fieldtype: "Link", options: "Customer", reqd: 1 },
				{ label: __("Qty"), fieldname: "qty", fieldtype: "Int", reqd: 1 },
				{ label: __("Rate"), fieldname: "rate", fieldtype: "Currency", reqd: 1 },
			],
			function (values) {
				frappe
					.call("frappe_livestock.api.sales.create_batch_sales_invoice", { batch: name, qty: values.qty, customer: values.customer, rate: values.rate })
					.then(function (r) {
						const m = r.message || {};
						frappe.msgprint(__("Invoice {0}: allocated {1}", [m.sales_invoice, m.allocated]));
						load(picker.get_value("batch"));
					})
					.fail(function () {
						// the server error toast is already shown; refresh so the
						// dashboard reflects the batch's actual state
						load(picker.get_value("batch"));
					});
			},
			__("Sell birds"),
			__("Sell")
		);
	}

	function do_open() {
		const name = need_batch();
		if (name) frappe.set_route("Form", "Livestock Batch", name);
	}

	frappe.pages["batch-dashboard"].on_page_show = function () {
		load(picker.get_value("batch"));
	};

	// Default to the most-recent active batch; never overwrite a user-picked batch.
	frappe.call("frappe_livestock.api.allocation.get_active_batches").then(function (r) {
		const batches = r.message || [];
		if (!batches.length || picker.get_value("batch")) return;
		picker.set_value("batch", batches[0].name);
	}).fail(function () {
		frappe.msgprint({ message: __("Could not load batches."), indicator: "orange" });
	});
};
