// Livestock Batch form: the stocking link — buy the batch's young stock in one
// action (full purchase chain, paid on the spot, allocated here as initial
// action (full purchase cycle, paid on the spot, allocated here as initial
frappe.ui.form.on("Livestock Batch", {
	refresh(frm) {
		if (frm.is_new()) {
			// cost), or link an already-paid stocking purchase invoice.
			frm.set_intro(__("<.stocking intro>"));
			return;
		}
		if (!frm.doc.stocking_purchase_invoice) {
			frm.add_custom_button(__("Buy stock"), () => show_buy_dialog(frm));
		}
	},
});

function show_buy_dialog(frm) {
	var company = frappe.defaults.get_user_default("company");
	var dialog = new frappe.ui.Dialog({
		title: __("Buy stock"),
		fields: [
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
			{ fieldname: "invoice_date", label: __("Invoice date"), fieldtype: "Date", default: "Today" },
			{
				fieldname: "mode_of_payment",
				label: __("Mode of payment"),
				fieldtype: "Link",
				options: "Mode of Payment",
				reqd: 1,
				default: "Cash",
			},
			{ fieldname: "invoice_number", label: __("Supplier invoice no."), fieldtype: "Data" },
		],
		primary_action_label: __("Buy {0} head", [frm.doc.quantity_placed]),
		primary_action(values) {
			frappe.call("frappe_livestock.api.stocking.create_stocking_purchase", {
				batch: frm.doc.name,
				supplier: values.supplier,
				warehouse: values.warehouse,
				rate: values.rate,
				company: company,
				invoice_date: values.invoice_date,
				mode_of_payment: values.mode_of_payment,
				invoice_number: values.invoice_number,
			}).then((r) => {
				dialog.hide();
				var made = r.message || {};
				frappe.msgprint(
					__("Stock purchased ({0}) and costed to this batch.", [made.purchase_invoice])
				);
				frm.reload_doc();
			});
		},
	});
	dialog.show();
}
