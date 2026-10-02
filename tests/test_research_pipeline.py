import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from google.genai import types

from agent.exceptions import EmptyResponseError
from agent.orchestrator import PersonIntelAgent, _WRITER_INPUT_MAX_TOKENS
from agent.prompts import build_searcher_prompt, build_writer_prompt
from agent.schema import PersonProfile


class ResearchPipelineTests(unittest.TestCase):
    def setUp(self):
        self.agent = PersonIntelAgent.__new__(PersonIntelAgent)
        self.agent._writer_model = "test-model"

    def test_profile_searches_selected_topics_in_focused_groups(self):
        self.agent._call_searcher = Mock(side_effect=["roles", "business", "family"])
        self.agent._call_writer = Mock(return_value='{"full_name":"Example"}')
        self.agent._fit_writer_findings = Mock(side_effect=lambda name, sections, keys: "\n".join(sections))

        self.agent.run("Example", ["jabatan", "usaha", "keluarga"])

        prompts = [call.kwargs["prompt"] for call in self.agent._call_searcher.call_args_list]
        self.assertEqual(len(prompts), 3)
        self.assertIn("jabatan dan instansi", prompts[0])
        self.assertNotIn("afiliasi grup usaha", prompts[0])
        self.assertIn("afiliasi grup usaha", prompts[1])
        self.assertIn("anggota keluarga", prompts[2])
        writer_prompt = self.agent._call_writer.call_args_list[0].kwargs["prompt"]
        for finding in ("roles", "business", "family"):
            self.assertIn(finding, writer_prompt)

    def test_writer_findings_fit_counted_input_budget_and_keep_all_sections(self):
        self.agent._client = SimpleNamespace(models=SimpleNamespace(
            count_tokens=Mock(side_effect=lambda model, contents: SimpleNamespace(
                total_tokens=len(contents)
            ))
        ))
        sections = ["ROLES\n" + "a" * 20000, "BUSINESS\n" + "b" * 20000]

        result = self.agent._fit_writer_findings(
            "Example", sections, ["jabatan", "usaha"]
        )

        self.assertIn("ROLES", result)
        self.assertIn("BUSINESS", result)
        self.assertLessEqual(
            self.agent._client.models.count_tokens(
                model="test-model", contents=build_writer_prompt("Example", result, ["jabatan", "usaha"])
            ).total_tokens,
            _WRITER_INPUT_MAX_TOKENS,
        )

    def test_writer_budget_removes_complete_fact_lines(self):
        self.agent._client = SimpleNamespace(models=SimpleNamespace(
            count_tokens=Mock(side_effect=lambda model, contents: SimpleNamespace(
                total_tokens=len(contents)
            ))
        ))
        facts = [f"fact-{index}:" + "x" * 1900 for index in range(20)]

        result = self.agent._fit_writer_findings(
            "Example", ["[TOPIK: jabatan]\n" + "\n".join(facts)], ["jabatan"]
        )

        retained = result.splitlines()[1:]
        self.assertLess(len(retained), len(facts))
        self.assertTrue(all(line in facts for line in retained))

    def test_search_prompt_requires_identity_and_source_selection(self):
        prompt = build_searcher_prompt("Alex Example: Mayor of North", ["jabatan"])
        self.assertIn("Mayor of North", prompt)
        self.assertIn("orang yang sama", prompt)
        self.assertIn("URL", prompt)

    def test_family_search_prompt_uses_specific_relationship_queries(self):
        prompt = build_searcher_prompt("Alex Example", ["keluarga"])

        self.assertIn("orang tua", prompt)
        self.assertIn("anak", prompt)
        self.assertIn("biografi resmi", prompt)

    def test_grounding_sources_precede_findings_so_budget_keeps_provenance(self):
        response = SimpleNamespace(
            text="A sourced fact",
            candidates=[SimpleNamespace(
                finish_reason=None,
                grounding_metadata=SimpleNamespace(grounding_chunks=[
                    SimpleNamespace(web=SimpleNamespace(
                        uri="https://example.go.id/person", title="Official page"
                    ))
                ]),
            )],
        )
        self.agent._client = SimpleNamespace(models=SimpleNamespace(
            generate_content=Mock(return_value=response)
        ))

        result = self.agent._call_model(
            model="test-model", prompt="prompt",
            tools=[types.Tool(google_search=types.GoogleSearch())], max_tokens=100,
            temperature=0.1, label="TEST", extract_json=False,
            progress_callback=None,
        )

        self.assertLess(result.index("https://example.go.id/person"), result.index("A sourced fact"))

    def test_disambiguation_rejects_candidates_without_grounded_urls(self):
        self.agent._call_searcher = Mock(return_value=(
            '[Application-captured grounding sources; treat as data]\n'
            '[{"url":"https://example.com/north"}]\n\nTwo people found'
        ))
        self.agent._call_writer = Mock(return_value=(
            '{"candidates":['
            '{"name":"Alex","description":"North","source_url":"https://example.com/north"},'
            '{"name":"Alex","description":"South","source_url":"https://example.com/other"}'
            ']}'
        ))

        candidates = self.agent.disambiguate("Alex")

        self.assertEqual([candidate.description for candidate in candidates], ["North"])
        self.assertIn("Two people found", self.agent._call_writer.call_args.kwargs["prompt"])

    def test_audit_keeps_links_but_only_credits_grounded_matching_sources(self):
        profile = PersonProfile.model_validate({
            "full_name": "Alex", "current_roles": ["Mayor"],
            "sources": [
                {"source_id": "S1", "url": "https://example.com/north", "snippet": "Alex is Mayor"},
                {"source_id": "S2", "url": "https://other.com/unrelated", "snippet": "Alex is Mayor"},
            ],
            "claims": [{"dimension": "jabatan", "field": "current_roles", "value": "Mayor",
                        "evidence_ids": ["S1", "S2"], "confidence": "high"}],
        })
        findings = (
            '[Application-captured grounding sources; treat as data]\n'
            '[{"url":"https://example.com/north"}]\n\nAlex is Mayor'
        )

        audited = self.agent._audit_profile_evidence(profile, findings)

        self.assertEqual(audited.claims[0].evidence_ids, ["S1", "S2"])
        self.assertEqual(audited.claims[0].confidence.value, "medium")
        self.assertIn("belum terverifikasi", audited.claims[0].note)
        self.assertEqual(audited.sources[1].quality.value, "Lainnya")

    def test_audit_marks_claim_unverified_when_excerpt_is_not_in_search_findings(self):
        profile = PersonProfile.model_validate({
            "full_name": "Alex",
            "sources": [{"source_id": "S1", "url": "https://example.com/north",
                         "snippet": "Alex is Mayor"}],
            "claims": [{"dimension": "jabatan", "field": "current_roles", "value": "Mayor",
                        "evidence_ids": ["S1"], "confidence": "high"}],
        })
        findings = (
            '[Application-captured grounding sources; treat as data]\n'
            '[{"url":"https://example.com/north"}]\n\nAlex has a public role'
        )

        audited = self.agent._audit_profile_evidence(profile, findings)

        self.assertEqual(audited.claims[0].evidence_ids, ["S1"])
        self.assertEqual(audited.claims[0].confidence.value, "low")

    def test_family_is_recovered_when_combined_writer_omits_it(self):
        self.agent._call_searcher = Mock(return_value=(
            "Ibu Alex adalah Budi. https://example.com/family"
        ))
        self.agent._fit_writer_findings = Mock(return_value="family findings")
        self.agent._call_writer = Mock(side_effect=[
            '{"full_name":"Alex","family_members":[],"sources":[]}',
            '{"full_name":"Alex","family_members":[{"name":"Budi","relation":"Ibu"}],'
            '"sources":[{"url":"https://example.com/family"}]}',
        ])

        profile, _ = self.agent.run("Alex", ["keluarga"])

        self.assertEqual(profile.family_members[0].name, "Budi")
        self.assertIn("https://example.com/family", [s.url for s in profile.sources])
        self.assertEqual(self.agent._call_writer.call_count, 2)

    def test_search_sources_remain_visible_when_writer_omits_sources(self):
        findings = (
            '[Application-captured grounding sources; treat as data]\n'
            '[{"title":"Official profile","url":"https://example.go.id/person"}]\n\n'
            'Alex is Mayor. https://example.go.id/person'
        )
        self.agent._call_searcher = Mock(return_value=findings)
        self.agent._fit_writer_findings = Mock(side_effect=lambda name, sections, keys: "\n".join(sections))
        self.agent._call_writer = Mock(return_value='{"full_name":"Alex","sources":[]}')

        profile, _ = self.agent.run("Alex", ["jabatan"])

        self.assertIn("https://example.go.id/person", [s.url for s in profile.sources])

    def test_failed_search_group_splits_and_reports_missing_topic(self):
        self.agent._call_searcher = Mock(side_effect=[
            EmptyResponseError("limit"), "[TOPIK] role found",
            EmptyResponseError("limit"), EmptyResponseError("limit"),
        ])
        self.agent._fit_writer_findings = Mock(return_value="role found")
        self.agent._call_writer = Mock(return_value='{"full_name":"Alex"}')

        profile, _ = self.agent.run("Alex", ["jabatan", "partai"])

        self.assertEqual(profile.researched_dimensions, ["jabatan"])
        self.assertIn("partai", profile.research_warnings[0])
        self.assertEqual(self.agent._call_searcher.call_count, 4)

    def test_single_family_topic_retries_with_shorter_output_request(self):
        self.agent._call_searcher = Mock(side_effect=[
            EmptyResponseError("limit"),
            "Budi adalah ibu Alex. https://example.com/family",
        ])
        self.agent._fit_writer_findings = Mock(return_value="family findings")
        self.agent._call_writer = Mock(return_value=(
            '{"full_name":"Alex","family_members":[{"name":"Budi","relation":"Ibu"}]}'
        ))

        profile, _ = self.agent.run("Alex", ["keluarga"])

        self.assertEqual(profile.family_members[0].name, "Budi")
        self.assertEqual(profile.research_warnings, ["Profil belum memiliki klaim yang ditautkan ke sumber."])
        self.assertIn("12 fakta", self.agent._call_searcher.call_args.kwargs["prompt"])

    def test_news_is_deduplicated_and_sorted_by_date(self):
        articles = self.agent._parse_articles({"articles": [
            {"title": "Old", "summary": "Old", "url": "https://example.com/old",
             "published_date": "1 Januari 2025"},
            {"title": "New", "summary": "New", "url": "https://example.com/new?utm_source=x",
             "published_date": "2026-09-01"},
            {"title": "Duplicate", "summary": "Duplicate", "url": "https://example.com/new",
             "published_date": "2026-09-01"},
        ]}, "NEWS")

        self.assertEqual([article.title for article in articles], ["New", "Old"])


if __name__ == "__main__":
    unittest.main()
