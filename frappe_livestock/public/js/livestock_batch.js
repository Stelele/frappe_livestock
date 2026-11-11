// Livestock Batch form: buy day-old stock through a dialog that builds the
// full purchase chain (order, receipt, invoice, payment) in one action,
// allocated to this batch as its initial cost.
frappe.ui.form.on("Livestock Batch", {
	refresh(frm) {
		if (frm.is_new()) {
			frm.set_intro(
				__("Buy day-old stock with Buy stock, or link an already-submitted stocking Purchase Invoice to set this batch's initial cost.")
			);
			return;
		}
		frm.add_custom_button(__("Buy stock"), () => show_buy_dialog(frm));
		frm.add_custom_button(__("View Dashboard"), () => {
			frappe.route_options = { batch: frm.doc.name };
			frappe.set_route("batch-dashboard");
		});
	},
});

function show_buy_dialog(frm) {
	var company = frappe.defaults.get_user_default("company");
	var fields = [];
	if (frm.doc.stocking_purchase_invoice) {
		fields.push({
			fieldname: "relink_note",
			fieldtype: "HTML",
			options:
				"<p class='text-muted'>" +
				__(
					"This will re-point the batch from {0} to the newly created stocking invoice. The server keeps an audit Comment on overwrites.",
					[frm.doc.stocking_purchase_invoice]
				) +
				"</p>",
		});
	}
	fields = fields.concat([
		{
			fieldname: "supplier",
			label: __("Supplier"),
			fieldtype: "Link",
			options: "Supplier",
			reqd: 1,
		},
		{
			fieldname: "warehouse",
			label: __("Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
			reqd: 1,
			get_query: { filters: [["is_group", "=", 0], ["company", "=", company]] },
		},
		{ fieldname: "rate", label: __("Rate per head"), fieldtype: "Currency", reqd: 1 },
		{ fieldname: "invoice_date", label: __("Invoice date"), fieldtype: "Date" },
		{
			fieldname: "mode_of_payment",
			label: __("Mode of payment"),
			fieldtype: "Link",
			options: "Mode of Payment",
			reqd: 1,
		},
		{ fieldname: "invoice_number", label: __("Supplier invoice no."), fieldtype: "Data" },
	]);
	var dialog = new frappe.ui.Dialog({
		title: __("Buy stock"),
		fields: fields,
		primary_action_label: __("Buy {0} head", [frm.doc.quantity_placed]),
		primary_action(values) {
			if (dialog._buy_busy) {
				return;
			}
			dialog._buy_busy = true;
			set_buy_busy(dialog, true);
			frappe
				.call("frappe_livestock.api.stocking.create_stocking_purchase", {
					batch: frm.doc.name,
					supplier: values.supplier,
					warehouse: values.warehouse,
					rate: values.rate,
					company: company,
					invoice_date: values.invoice_date,
					mode_of_payment: values.mode_of_payment,
					invoice_number: values.invoice_number,
				})
				.then((r) => {
					var made = r.message || {};
					dialog.hide();
					frappe.msgprint(
						__("Stock purchased ({0}) and costed to this batch.", [made.purchase_invoice])
					);
					frm.reload_doc();
					finish_buy(dialog);
				})
				.fail(() => {
					// Server error text is already shown by frappe.call's
					// default error handler; just release the dialog.
					finish_buy(dialog);
				});
		},
	});
	dialog.show();
	// v16 FieldGroup.get_values() only applies df.default with include_default,
	// so dialog defaults are applied explicitly via set_value below.
	dialog.set_value("invoice_date", frappe.datetime.get_today());
	// Dialog defaults come from get_purchase_context resolved when the dialog
	// opens (not cached at page load), so a changed user default applies.
	frappe
		.call("frappe_livestock.api.settings.get_purchase_context")
		.then((r) => {
			var ctx = r.message || {};
			if (ctx.warehouse && !dialog.get_value("warehouse")) {
				dialog.set_value("warehouse", ctx.warehouse);
			}
			if (ctx.mode_of_payment && !dialog.get_value("mode_of_payment")) {
				dialog.set_value("mode_of_payment", ctx.mode_of_payment);
			}
			if ((ctx.warnings || []).length) {
				frappe.msgprint({
					title: __("Setup warnings"),
					message: "<ul><li>" + ctx.warnings.map(frappe.utils.escape_html).join("</li><li>") + "</li></ul>",
					indicator: "orange",
				});
			}
		})
		.fail(() => {
			frappe.msgprint({
				message: __("Purchase defaults could not load; the dialog is still usable, pick values manually."),
				indicator: "orange",
			});
		});
}

function set_buy_busy(dialog, on) {
	if (
		typeof dialog.disable_primary_action === "function" &&
		typeof dialog.enable_primary_action === "function"
	) {
		if (on) {
			dialog.disable_primary_action();
		} else {
			dialog.enable_primary_action();
		}
	} else {
		var btns =
			typeof dialog.get_primary_btn === "function"
				? dialog.get_primary_btn()
				: dialog.$wrapper.find(".btn-primary");
		btns.prop("disabled", on);
		btns.toggleClass("disabled", on);
	}
	if (on) {
		frappe.freeze(__("Buying stock…"));
	} else {
		frappe.unfreeze();
	}
}

function finish_buy(dialog) {
	dialog._buy_busy = false;
	set_buy_busy(dialog, false);
}
