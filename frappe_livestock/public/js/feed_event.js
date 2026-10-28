frappe.ui.form.on("Feed Event", {
	onload(frm) {
		if (!frm.is_new() || frm.doc.flock) {
			return;
		}
		if (!frm.doc.date) {
			frm.set_value("date", frappe.datetime.get_today());
		}
		frappe.call("frappe_livestock.api.allocation.get_active_flocks").then((r) => {
			const flocks = r.message || [];
			if (!flocks.length || frm.doc.flock) {
				return;
			}
			frm.set_value("flock", flocks[0].name);
		});
	},
});
