import frappe
from frappe.model.document import Document


class LivestockType(Document):
	pass


def _stage_value(stage, key):
	if isinstance(stage, dict):
		return stage.get(key)
	return getattr(stage, key, None)


def get_stage_for_age(stages: list[dict], age_days: int) -> dict | None:
	"""Return the stage covering `age_days`, or clamp past the final stage.

	Returns a dict of {"stage_name", "start_day", "end_day"} for the first
	stage where start_day <= age_days <= end_day. If `age_days` is past the
	greatest end_day, returns the last stage (by start_day). Returns None
	for negative ages, empty stage lists, or ages falling in a gap.
	"""
	if age_days is None or age_days < 0:
		return None

	rows = [
		{
			"stage_name": _stage_value(stage, "stage_name"),
			"start_day": _stage_value(stage, "start_day"),
			"end_day": _stage_value(stage, "end_day"),
		}
		for stage in (stages or [])
	]

	if not rows:
		return None

	for row in rows:
		if row["start_day"] <= age_days <= row["end_day"]:
			return row

	if age_days > max(row["end_day"] for row in rows):
		return sorted(rows, key=lambda row: row["start_day"])[-1]

	return None
