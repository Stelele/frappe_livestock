// Shared form handlers, registered once per session by the global guard below.
function livestock_default_batch(frm, after_batch) {
	if (!frm.is_new() || frm.doc.batch) {
		return;
	}
	if (!frm.doc.date) {
		frm.set_value("date", frappe.datetime.get_today());
	}
	frappe
		.call("frappe_livestock.api.allocation.get_active_batches")
		.then((r) => {
			const batches = r.message || [];
			// Post-resolve guard: the pre-call check above races user input,
			// so re-check here and never stomp a batch the user just picked.
			if (!batches.length || frm.doc.batch) {
				return;
			}
			const row = batches[0];
			frm.set_value("batch", row.name);
			livestock_show_remaining_alert(frm, row);
			if (after_batch) {
				after_batch(frm);
			}
		})
		.fail(() => {
			// Intentionally silent: a missing default must not block entry.
		});
}

function livestock_show_remaining_alert(frm, row) {
	if (!row || frm._livestock_remaining_alert_shown) {
		return;
	}
	frm._livestock_remaining_alert_shown = true;
	frappe.show_alert({
		message: __("Batch {0}: {1} birds remain", [row.name, row.remaining]),
		indicator: "blue",
	});
}

function livestock_prefill_feed_item(frm) {
	if (!frm.doc.batch || frm.doc.feed_item) {
		return;
	}
	frappe.db
		.get_list("Feed Event", {
			filters: { batch: frm.doc.batch },
			fields: ["feed_item"],
			order_by: "date desc",
			limit: 1,
		})
		.then((rows) => {
			if (!rows || !rows.length || !rows[0].feed_item) {
				return;
			}
			// Guard again: the user may have picked an item while we waited.
			if (frm.doc.feed_item) {
				return;
			}
			frm.set_value("feed_item", rows[0].feed_item);
		})
		.fail(() => {
			// Intentionally silent: never block on a wrong-guess lookup.
		});
}

function livestock_set_batch_query(frm) {
	frm.set_query("batch", () => ({ filters: [["status", "!=", "Closed"]] }));
}

if (!window.__livestock_forms_registered) {
	window.__livestock_forms_registered = true;
	frappe.ui.form.on("Feed Event", {
		onload(frm) {
			livestock_set_batch_query(frm);
			livestock_default_batch(frm, livestock_prefill_feed_item);
		},
		batch(frm) {
			livestock_prefill_feed_item(frm);
		},
	});

	frappe.ui.form.on("Mortality", {
		onload(frm) {
			livestock_set_batch_query(frm);
			livestock_default_batch(frm);
		},
	});

	frappe.ui.form.on("Livestock Weight", {
		onload(frm) {
			livestock_set_batch_query(frm);
			livestock_default_batch(frm);
		},
	});
}
