frappe.ui.form.on("Feed Event", {
	onload(frm) {
		if (!frm.is_new() || frm.doc.batch) {
			return;
		}
		if (!frm.doc.date) {
			frm.set_value("date", frappe.datetime.get_today());
		}
		frappe.call("frappe_livestock.api.allocation.get_active_batches").then((r) => {
			const batches = r.message || [];
			if (!batches.length || frm.doc.batch) {
				return;
			}
			frm.set_value("batch", batches[0].name);
		});
	},
});
