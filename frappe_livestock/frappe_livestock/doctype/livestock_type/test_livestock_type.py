import frappe
from frappe.tests import IntegrationTestCase
from frappe_livestock.frappe_livestock.doctype.livestock_type.livestock_type import get_stage_for_age

BROILER_STAGES = [
	{"stage_name": "Day Old Chick", "start_day": 0, "end_day": 20},
	{"stage_name": "Grower", "start_day": 21, "end_day": 41},
	{"stage_name": "Broiler", "start_day": 42, "end_day": 48},
]

# The `finished_item` Link pulls Item (and its whole ERPNext fixture chain,
# whose import-time bootstrap conflicts with existing dev-site data) into
# automatic test-record generation. These tests never need Item records.
IGNORE_TEST_RECORD_DEPENDENCIES = ["Item"]


def ensure_broiler_type():
	if not frappe.db.exists("Livestock Type", "Broiler"):
		frappe.get_doc(
			{
				"doctype": "Livestock Type",
				"livestock_type_name": "Broiler",
				"stages": BROILER_STAGES,
			}
		).insert(ignore_if_duplicate=True)


class TestLivestockType(IntegrationTestCase):
	def test_stage_boundaries(self):
		self.assertEqual(get_stage_for_age(BROILER_STAGES, 0)["stage_name"], "Day Old Chick")
		self.assertEqual(get_stage_for_age(BROILER_STAGES, 20)["stage_name"], "Day Old Chick")
		self.assertEqual(get_stage_for_age(BROILER_STAGES, 21)["stage_name"], "Grower")
		self.assertEqual(get_stage_for_age(BROILER_STAGES, 41)["stage_name"], "Grower")
		self.assertEqual(get_stage_for_age(BROILER_STAGES, 42)["stage_name"], "Broiler")

	def test_stage_clamps_to_last_stage_past_final(self):
		self.assertEqual(get_stage_for_age(BROILER_STAGES, 60)["stage_name"], "Broiler")

	def test_negative_age_returns_none(self):
		self.assertIsNone(get_stage_for_age(BROILER_STAGES, -1))

	def test_broiler_type_is_seeded(self):
		ensure_broiler_type()
		self.assertTrue(frappe.db.exists("Livestock Type", "Broiler"))
