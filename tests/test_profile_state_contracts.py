import unittest

from pydantic import ValidationError

from agent.schema import PersonProfile
from ui.components import flag_badge
from ui.report_renderer import _dimension_researched, _job_history_rows
from utils.cache import (
    build_profile_cache_key,
    clear_research_state,
    profile_revision,
    profile_session_label,
)


class ProfileKnowledgeStateTests(unittest.TestCase):
    def test_unavailable_classifications_remain_unknown(self):
        profile = PersonProfile.model_validate(
            {
                "full_name": "Example",
                "is_minister": None,
                "tni_polri": {"is_tni_polri": None},
            }
        )

        self.assertIsNone(profile.is_minister)
        self.assertIsNone(profile.tni_polri.is_tni_polri)
        self.assertIsNone(profile.field_confidence.jabatan_khusus)

    def test_unresearched_dimension_is_distinct_from_researched_dimension(self):
        profile = PersonProfile(
            full_name="Example",
            researched_dimensions=["jabatan"],
        )

        self.assertTrue(_dimension_researched(profile, "jabatan"))
        self.assertFalse(_dimension_researched(profile, "usaha"))

    def test_unknown_classification_has_an_explicit_label(self):
        html = flag_badge("Menteri", None)

        self.assertIn("Tidak diketahui", html)

    def test_missing_job_end_date_is_not_presented_as_current(self):
        profile = PersonProfile.model_validate(
            {
                "full_name": "Example",
                "job_history": [
                    {"title": "Advisor", "company": "Example Company"}
                ],
            }
        )

        rows = _job_history_rows(profile)

        self.assertEqual(rows[0]["Selesai"], "Tidak diketahui")

    def test_profile_rejects_duplicate_source_ids(self):
        with self.assertRaises(ValidationError):
            PersonProfile.model_validate(
                {
                    "full_name": "Example",
                    "sources": [
                        {"source_id": "S1", "url": "https://example.com/one"},
                        {"source_id": "S1", "url": "https://example.com/two"},
                    ],
                }
            )

    def test_profile_rejects_claims_with_unknown_sources(self):
        with self.assertRaises(ValidationError):
            PersonProfile.model_validate(
                {
                    "full_name": "Example",
                    "sources": [
                        {"source_id": "S1", "url": "https://example.com/one"}
                    ],
                    "claims": [
                        {
                            "field": "current_roles",
                            "value": "Minister",
                            "evidence_ids": ["S2"],
                        }
                    ],
                }
            )


class ProfileStateKeyTests(unittest.TestCase):
    def test_cache_key_includes_identity_dimensions_and_models(self):
        base = build_profile_cache_key(
            "Alex Example, Mayor of North",
            ["jabatan"],
            "search-model-a",
            "writer-model-a",
        )

        self.assertNotEqual(
            base,
            build_profile_cache_key(
                "Alex Example, Mayor of South",
                ["jabatan"],
                "search-model-a",
                "writer-model-a",
            ),
        )
        self.assertNotEqual(
            base,
            build_profile_cache_key(
                "Alex Example, Mayor of North",
                ["usaha", "jabatan"],
                "search-model-a",
                "writer-model-a",
            ),
        )
        self.assertNotEqual(
            base,
            build_profile_cache_key(
                "Alex Example, Mayor of North",
                ["jabatan"],
                "search-model-b",
                "writer-model-a",
            ),
        )

    def test_same_name_profiles_get_distinct_session_labels(self):
        north = PersonProfile(full_name="Alex Example", identity_context="Mayor of North")
        south = PersonProfile(full_name="Alex Example", identity_context="Mayor of South")

        self.assertNotEqual(profile_session_label(north), profile_session_label(south))

    def test_profile_revision_changes_when_profile_content_changes(self):
        before = PersonProfile(full_name="Example", current_roles=["Role A"])
        after = PersonProfile(full_name="Example", current_roles=["Role B"])

        self.assertNotEqual(profile_revision(before), profile_revision(after))

    def test_clear_research_state_preserves_configuration(self):
        state = {
            "api_key": "user-key",
            "searcher_model": "search-model",
            "writer_model": "writer-model",
            "profile_cache": {"one": object()},
            "searched_profiles": {"one": object()},
            "last_profile": object(),
            "summary_revision": "summary",
            "news_person_revision": [],
            "news_company_revision": [],
            "disambig_pending": True,
            "identity_resolutions": {"example": {}},
        }

        clear_research_state(state)

        self.assertEqual(
            state,
            {
                "api_key": "user-key",
                "searcher_model": "search-model",
                "writer_model": "writer-model",
            },
        )


if __name__ == "__main__":
    unittest.main()
