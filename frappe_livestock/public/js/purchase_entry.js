// Livestock Purchase: one click creates/submits PO -> Receipt -> Invoice ->
// Payment (supplier paid in full), then allocates bags across batches so
// cost-per-head stays live. Sole `on_page_load` owner via the `page_js` hook.
frappe.pages["purchase-entry"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({ parent: wrapper, title: __("Livestock Purchase"), single_column: true });
	// Context resolved once per page entry; company re-read inside the create
	// handler so a stale user default cannot leak into the purchase chain.
	var ctx = { company: null, warehouse: null, mode_of_payment: null };
	var item_rows = [], allocate_rows = [], creating = false, allocating = false;

	page.body.empty();
	page.body.append(
		`<div class="frappe-card"><div class="widget-head"><div class="widget-title">${__("Buy")}</div></div>` +
		`<p class="text-muted">${__("Enter what you bought. One click creates and submits PO, receipt, invoice and payment.")}</p>` +
		`<div class="purchase-head-fields"></div><div class="purchase-item-rows"></div></div>` +
		`<div class="frappe-card"><div class="widget-head"><div class="widget-title">${__("Allocate to batches")}</div></div>` +
		`<p class="text-muted">${__("Split a purchase's bags between the batches they apply to. Cost per head updates immediately.")}</p>` +
		`<div class="allocate-head-fields"></div><div class="allocate-item-rows"></div></div>`
	);

	function F(name, label, type, opts) {
		return Object.assign({ fieldname: name, label: __(label), fieldtype: type }, opts || {});
	}
	function CB() { return { fieldtype: "Column Break" }; }
	function company_filter(extra) {
		return function () { return ctx.company ? { filters: extra.concat([["company", "=", ctx.company]]) } : {}; };
	}
	function row_fields(left, right) {
		return [F("item_code", "Item", "Link", { options: "Item", reqd: 1 }), CB(), left, CB(), right];
	}
	function new_row(mount, fields) {
		var fg = new frappe.ui.FieldGroup({ parent: $("<div></div>").appendTo(mount).get(0), fields: fields });
		fg.make();
		return fg;
	}
	function set_row(fg, d) {
		if (!d) return;
		if (d.item_code) fg.fields_dict.item_code.set_input(d.item_code);
		if (d.batch) fg.fields_dict.batch.set_input(d.batch);
		if (d.qty) fg.fields_dict.qty.set_input(d.qty);
		if (d.rate) fg.fields_dict.rate.set_input(d.rate);
	}
	// Buy section
	var purchase_head = new frappe.ui.FieldGroup({
		parent: page.body.find(".purchase-head-fields").get(0),
		fields: [
			F("supplier", "Supplier", "Link", { options: "Supplier", reqd: 1 }), CB(),
			F("warehouse", "Warehouse", "Link", { options: "Warehouse", reqd: 1, get_query: company_filter([["is_group", "=", 0]]) }), CB(),
			F("invoice_date", "Invoice date", "Date"), CB(),
			F("mode_of_payment", "Mode of payment", "Link", { options: "Mode of Payment", reqd: 1 }), CB(),
			F("invoice_number", "Supplier invoice no.", "Data"),
		],
	});
	purchase_head.make();
	function add_item_row(d) {
		var fg = new_row(page.body.find(".purchase-item-rows"), row_fields(
			F("qty", "Qty", "Float", { reqd: 1 }), F("rate", "Rate", "Currency", { reqd: 1 })));
		set_row(fg, d);
		item_rows.push(fg);
		return fg;
	}
	function collect(fgs, need) {
		var out = [], incomplete = false;
		fgs.forEach(function (fg) {
			var v = fg.get_values();
			if (!v || !v.item_code || !v.qty || (need && !v[need])) { incomplete = true; return; }
			out.push(v);
		});
		return { rows: out, incomplete: incomplete };
	}
	function incomplete_msg() {
		frappe.msgprint({ message: __("Some rows are incomplete — fill every item, batch and qty row or remove it."), indicator: "orange" });
	}
	function finish_create() { creating = false; create_btn.prop("disabled", false); frappe.unfreeze(); }
	function on_create() {
		if (creating) return;
		var values = purchase_head.get_values();
		if (!values) return;
		var items = collect(item_rows);
		if (items.incomplete) { incomplete_msg(); return; }
		var payload = items.rows.map(function (v) { return { item_code: v.item_code, qty: v.qty, rate: v.rate }; });
		if (!payload.length) { frappe.msgprint(__("Enter at least one item.")); return; }
		creating = true;
		create_btn.prop("disabled", true);
		frappe.freeze(__("Creating purchase…"));
		frappe.call("frappe_livestock.api.settings.get_purchase_context")
			.then(function (r) {
				var c = r.message || {};
				return frappe.call("frappe_livestock.api.purchase.create_full_purchase", {
					company: c.company, supplier: values.supplier, warehouse: values.warehouse, items: payload,
					invoice_number: values.invoice_number, invoice_date: values.invoice_date, mode_of_payment: values.mode_of_payment,
				});
			})
			.then(function (r) {
				var made = r.message || {};
				frappe.msgprint([
					__("Purchase Order: {0}", [made.purchase_order]), __("Purchase Receipt: {0}", [made.purchase_receipt]),
					__("Purchase Invoice: {0}", [made.purchase_invoice]), __("Payment Entry: {0}", [made.payment_entry]),
				].join("<br>"));
				allocate_head.fields_dict.purchase_invoice.set_input(made.purchase_invoice);
				load_invoice_lines(made.purchase_invoice);
				finish_create();
			})
			.fail(finish_create);
	}
	// Allocate section
	var allocate_head = new frappe.ui.FieldGroup({
		parent: page.body.find(".allocate-head-fields").get(0),
		fields: [F("purchase_invoice", "Purchase invoice", "Link", { options: "Purchase Invoice", reqd: 1, get_query: company_filter([["docstatus", "=", 1]]) })],
	});
	allocate_head.make();
	function add_alloc_row(d) {
		var fg = new_row(page.body.find(".allocate-item-rows"), row_fields(
			F("batch", "Livestock Batch", "Link", { options: "Livestock Batch", reqd: 1 }), F("qty", "Qty", "Float", { reqd: 1 })));
		set_row(fg, d);
		allocate_rows.push(fg);
		return fg;
	}
	function clear_alloc_rows() { page.body.find(".allocate-item-rows").empty(); allocate_rows.length = 0; }
	// Takes the invoice as a param: callers pass the value they already hold,
	// so there is no set_input -> get_value race on the Link control.
	function load_invoice_lines(invoice) {
		if (!invoice) { frappe.msgprint(__("Pick a purchase invoice first.")); return; }
		frappe.db.get_doc("Purchase Invoice", invoice).then(function (doc) {
			if (!doc || !doc.items || !doc.items.length) { frappe.msgprint(__("No item lines on this invoice.")); return; }
			// Intentionally silent on failure: allocate rows stay empty and the
			// user can add them by hand via "Add row (allocate)".
			frappe.call("frappe_livestock.api.allocation.get_active_batches").then(function (r) {
				var batches = r.message || [], single = batches.length === 1 ? batches[0].name : null;
				clear_alloc_rows();
				doc.items.forEach(function (line) { add_alloc_row({ item_code: line.item_code, qty: line.qty, batch: single }); });
			});
		}).catch(function () {
			frappe.msgprint({ message: __("Could not load invoice lines."), indicator: "orange" });
		});
	}
	function is_overwrite_error(err) {
		var s = "";
		try { s = JSON.stringify(err) || ""; } catch (e) { s = ""; }
		return (s + " " + ((err && err.message) || "") + " " + ((err && err.exc) || "")).indexOf("Confirm overwrite to proceed.") !== -1;
	}
	function finish_allocate() { allocating = false; alloc_btn.prop("disabled", false); frappe.unfreeze(); }
	function submit_allocations(invoice, allocations, force) {
		frappe.call("frappe_livestock.api.allocation.split_purchase_to_batches", {
			purchase_invoice: invoice, allocations: allocations, force: force ? 1 : 0,
		}).then(function (r) {
			var made = r.message || {};
			frappe.msgprint({ message: __("Batch Cost {0} — cost per head is live on the dashboard.", [made.batch_cost]), indicator: "green" });
			finish_allocate();
		}).fail(function (err) {
			if (!force && is_overwrite_error(err)) {
				frappe.confirm(__("Overwrite existing Batch Cost for {0} with these rows?", [frappe.utils.escape_html(invoice)]),
					function () { submit_allocations(invoice, allocations, 1); }, finish_allocate);
			} else finish_allocate();
		});
	}
	function on_allocate() {
		if (allocating) return;
		var invoice = allocate_head.fields_dict.purchase_invoice.get_value();
		if (!invoice) { frappe.msgprint(__("Pick a purchase invoice first.")); return; }
		var allocations = collect(allocate_rows, "batch");
		if (allocations.incomplete) { incomplete_msg(); return; }
		var payload = allocations.rows.map(function (v) { return { item_code: v.item_code, batch: v.batch, qty: v.qty }; });
		if (!payload.length) { frappe.msgprint(__("Fill at least one row: item, batch and qty.")); return; }
		allocating = true;
		alloc_btn.prop("disabled", true);
		frappe.freeze(__("Allocating purchase…"));
		submit_allocations(invoice, payload, 0);
	}
	// Buttons + per-visit context
	var create_btn = $(page.set_primary_action(__("Create purchase"), on_create));
	page.add_inner_button(__("Add row"), add_item_row);
	page.add_inner_button(__("Add row (allocate)"), add_alloc_row);
	page.add_inner_button(__("Load invoice lines"), function () {
		load_invoice_lines(allocate_head.fields_dict.purchase_invoice.get_value());
	});
	var alloc_btn = $(page.add_inner_button(__("Allocate to batches"), on_allocate, null, "primary"));
	add_item_row();
	add_alloc_row();
	frappe.call("frappe_livestock.api.settings.get_purchase_context").then(function (r) {
		ctx = r.message || {};
		// FieldGroup.get_values() only applies df.default when include_default is
		// set, so dead `default:` keys were removed above and defaults are set
		// here instead — only into still-empty fields so user input is kept.
		if (ctx.warehouse && !purchase_head.fields_dict.warehouse.get_value()) purchase_head.fields_dict.warehouse.set_value(ctx.warehouse);
		if (ctx.mode_of_payment && !purchase_head.fields_dict.mode_of_payment.get_value()) purchase_head.fields_dict.mode_of_payment.set_value(ctx.mode_of_payment);
		purchase_head.fields_dict.invoice_date.set_value(frappe.datetime.get_today());
		if ((ctx.warnings || []).length) {
			frappe.msgprint({ title: __("Setup warnings"), message: "<ul><li>" + ctx.warnings.join("</li><li>") + "</li></ul>", indicator: "orange" });
		}
	}).fail(function () {
		purchase_head.fields_dict.invoice_date.set_value(frappe.datetime.get_today());
		frappe.msgprint({ message: __("Could not load purchase defaults."), indicator: "orange" });
	});
};
