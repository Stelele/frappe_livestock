// Flock form: the "Day-old chicks" link — buy the chicks for THIS flock in one
// action (full purchase chain, paid on the spot, allocated here as initial
// cost), or link an already-paid chick purchase invoice.
frappe.ui.form.on("Flock", {
	refresh(frm) {
		if (frm.is_new()) {
			// save the flock first: the chick purchase needs quantity_placed
			frm.set_intro(__("Save the flock to record its day-old chicks."));
			return;
		}
		if (!frm.doc.chick_purchase_invoice) {
			frm.add_custom_button(__("Buy day-old chicks"), () => show_buy_dialog(frm));
		}
	},
});

function show_buy_dialog(frm) {
	var company = frappe.defaults.get_user_default("company");
	var dialog = new frappe.ui.Dialog({
		title: __("Buy day-old chicks"),
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
			{ fieldname: "rate", label: __("Rate per chick"), fieldtype: "Currency", reqd: 1 },
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
		primary_action_label: __("Buy {0} chicks", [frm.doc.quantity_placed]),
		primary_action(values) {
			frappe.call("frappe_livestock.api.chicks.create_chick_purchase", {
				flock: frm.doc.name,
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
					__("Chicks purchased ({0}) and costed to this flock.", [made.purchase_invoice])
				);
				frm.reload_doc();
			});
		},
	});
	dialog.show();
}
