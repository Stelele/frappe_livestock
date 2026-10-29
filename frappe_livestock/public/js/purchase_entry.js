// Livestock Purchase page: record a purchase in one action (PO -> Receipt ->
// Invoice -> Payment, supplier paid in full on the spot) and allocate its bags
// across the flocks they apply to, so cost-per-bird stays live. Loaded on the
// purchase-entry page via the `page_js` hook (appended last, so this definition
// sticks), mirroring flock_dashboard.js.
frappe.pages["purchase-entry"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Livestock Purchase"),
		single_column: true,
	});

	var company = frappe.defaults.get_user_default("company");
	var last_invoice = null;
	var item_rows = [];
	var allocate_rows = [];

	page.body.empty();
	page.body.append(
		`<h4>${__("Buy")}</h4>
		 <div class="purchase-head-fields"></div>
		 <p class="form-text">${__("Enter what you bought. One click creates and submits PO, receipt, invoice and payment.")}</p>
		 <div class="purchase-item-rows"></div>
		 <p class="text-muted">
			 <button class="btn btn-secondary btn-xs" id="add-item-row">${__("Add row")}</button>
		 </p>
		 <p><button class="btn btn-primary" id="create-purchase">${__("Create purchase")}</button></p>
		 <hr>
		 <h4>${__("Allocate to flocks")}</h4>
		 <p class="text-muted form-text">${__("Split a purchase's bags between the flocks they apply to. Cost per bird updates immediately.")}</p>
		 <div class="allocate-head-fields"></div>
		 <div class="allocate-item-rows"></div>
		 <p class="text-muted">
			 <button class="btn btn-secondary btn-xs" id="add-allocate-row">${__("Add row")}</button>
			 <button class="btn btn-secondary btn-xs" id="load-invoice-lines">${__("Load invoice lines")}</button>
		 </p>
		 <p><button class="btn btn-primary" id="allocate-purchase">${__("Allocate")}</button></p>`
	);

	function make_row($parent, fields) {
		var fg = new frappe.ui.FieldGroup({ parent: $parent.get(0), fields: fields });
		fg.make();
		return fg;
	}

	function make_field(df) {
		return { fieldname: df.name, label: __(df.label), fieldtype: df.type, options: df.options || null, reqd: df.reqd ? 1 : 0, default: df.default || undefined, get_query: df.query || undefined };
	}

	// ---------------------------------------------------------------
	// Buy section
	// ---------------------------------------------------------------
	var purchase_head = new frappe.ui.FieldGroup({
		parent: page.body.find(".purchase-head-fields").get(0),
		fields: [
			make_field({ name: "supplier", label: "Supplier", type: "Link", options: "Supplier", reqd: 1 }),
			{ fieldtype: "Column Break" },
			make_field({
				name: "warehouse", label: "Warehouse", type: "Link", options: "Warehouse", reqd: 1,
				query: { filters: [["is_group", "=", 0], ["company", "=", company]] },
			}),
			{ fieldtype: "Column Break" },
			make_field({ name: "invoice_date", label: "Invoice date", type: "Date", default: "Today" }),
			{ fieldtype: "Column Break" },
			make_field({ name: "mode_of_payment", label: "Mode of payment", type: "Link", options: "Mode of Payment", reqd: 1, default: "Cash" }),
			{ fieldtype: "Column Break" },
			make_field({ name: "invoice_number", label: "Supplier invoice no.", type: "Data" }),
		],
	});
	purchase_head.make();

	function item_row() {
		var $row = $('<div class="purchase-item-row"></div>').appendTo(page.body.find(".purchase-item-rows"));
		var fg = make_row($row, [
			make_field({ name: "item_code", label: "Item", type: "Link", options: "Item", reqd: 1 }),
			{ fieldtype: "Column Break" },
			make_field({ name: "qty", label: "Qty", type: "Int", reqd: 1 }),
			{ fieldtype: "Column Break" },
			make_field({ name: "rate", label: "Rate", type: "Currency", reqd: 1 }),
		]);
		item_rows.push(fg);
		return fg;
	}

	page.body.find("#add-item-row").on("click", item_row);
	item_row();

	function collect_items() {
		// Read straight from the row DOM: frappe controls carry their fieldname
		// on every input, and the server (_validate_purchase_inputs) is the
		// single source of truth for item existence and rates.
		var items = [];
		page.body.find(".purchase-item-rows .purchase-item-row").each(function () {
			var row = $(this);
			var item_code = row.find("input[data-fieldname='item_code']").val();
			if (!item_code) {
				return;
			}
			items.push({
				item_code: item_code,
				qty: flt(row.find("input[data-fieldname='qty']").val()),
				rate: flt(row.find("input[data-fieldname='rate']").val()),
			});
		});
		return items;
	}

	page.body.find("#create-purchase").on("click", function () {
		var values = purchase_head.get_values();
		if (!values) {
			// FieldGroup flags missing reqd fields in its own message banner
			return;
		}
		var items = collect_items();
		if (!items.length) {
			frappe.msgprint(__("Enter at least one item."));
			return;
		}

		frappe.call("frappe_livestock.api.purchase.create_full_purchase", {
			company: company,
			supplier: values.supplier,
			warehouse: values.warehouse,
			items: items,
			invoice_number: values.invoice_number,
			invoice_date: values.invoice_date,
			mode_of_payment: values.mode_of_payment,
		}).then(function (r) {
			var made = r.message || {};
			last_invoice = made.purchase_invoice;
			allocate_head.fields_dict.purchase_invoice.set_input(last_invoice);
			// prefill allocation rows from the fresh invoice's own lines
			load_invoice_lines();
			frappe.msgprint(
				__("Created and submitted:") +
					`<br>${made.purchase_order} → ${made.purchase_receipt} → ${made.purchase_invoice} → ${made.payment_entry}`
			);
		});
	});

	// ---------------------------------------------------------------
	// Allocate to flocks
	// ---------------------------------------------------------------
	var allocate_head = new frappe.ui.FieldGroup({
		parent: page.body.find(".allocate-head-fields").get(0),
		fields: [
			make_field({
				name: "purchase_invoice", label: "Purchase invoice", type: "Link", options: "Purchase Invoice", reqd: 1,
				query: { filters: [["company", "=", company], ["docstatus", "=", 1]] },
			}),
		],
	});
	allocate_head.make();

	function clear_alloc_rows() {
		page.body.find(".allocate-item-rows").empty();
		allocate_rows.length = 0;
		alloc_row();
	}

	function alloc_row(values) {
		var $row = $('<div class="allocate-item-row"></div>').appendTo(page.body.find(".allocate-item-rows"));
		var fg = make_row($row, [
			make_field({ name: "item_code", label: "Item", type: "Link", options: "Item", reqd: 1 }),
			{ fieldtype: "Column Break" },
			make_field({ name: "flock", label: "Flock", type: "Link", options: "Flock", reqd: 1 }),
			{ fieldtype: "Column Break" },
			make_field({ name: "qty", label: "Qty", type: "Float", reqd: 1 }),
		]);
		allocate_rows.push(fg);
		if (values) {
			fg.fields_dict.item_code.set_input(values.item_code);
			if (values.flock) {
				fg.fields_dict.flock.set_input(values.flock);
			}
			fg.fields_dict.qty.set_input(values.qty);
		}
		return fg;
	}

	page.body.find("#add-allocate-row").on("click", function () {
		alloc_row();
	});

	function load_invoice_lines() {
		var invoice = allocate_head.fields_dict.purchase_invoice.get_value();
		if (!invoice) {
			frappe.msgprint(__("Pick a purchase invoice first."));
			return;
		}
		// full doc read: client get_list strips child-table fields, get_doc doesn't
		frappe.db.get_doc("Purchase Invoice", invoice).then(function (doc) {
			if (!doc || !doc.items || !doc.items.length) {
				frappe.msgprint(__("No item lines on this invoice."));
				return;
			}
			clear_alloc_rows();
			page.body.find(".allocate-item-rows").empty();
			allocate_rows.length = 0;
			doc.items.forEach(function (line) {
				alloc_row({ item_code: line.item_code, qty: line.qty });
			});
		});
	}

	page.body.find("#load-invoice-lines").on("click", load_invoice_lines);

	page.body.find("#allocate-purchase").on("click", function () {
		var invoice = allocate_head.fields_dict.purchase_invoice.get_value();
		if (!invoice) {
			frappe.msgprint(__("Pick a purchase invoice first."));
			return;
		}
		var allocations = [];
		page.body.find(".allocate-item-rows .allocate-item-row").each(function () {
			var row = $(this);
			var item_code = row.find("input[data-fieldname='item_code']").val();
			var flock = row.find("input[data-fieldname='flock']").val();
			if (!item_code || !flock) {
				return;
			}
			allocations.push({
				item_code: item_code,
				flock: flock,
				qty: flt(row.find("input[data-fieldname='qty']").val()),
			});
		});
		if (!allocations.length) {
			frappe.msgprint(__("Fill at least one row: item, flock and qty."));
			return;
		}
		frappe.call("frappe_livestock.api.allocation.split_purchase_to_flocks", {
			purchase_invoice: invoice,
			allocations: allocations,
		}).then(function (r) {
			var made = r.message || {};
			frappe.msgprint(
				__("Allocated to flocks — Flock Cost {0}. Cost per bird is live on the dashboard.", [
					made && made.name ? made.name : invoice,
				])
			);
		});
	});
};
