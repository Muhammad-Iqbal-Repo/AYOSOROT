import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
from google.genai import errors as genai_errors

from agent import orchestrator
from agent.exceptions import (
    EmptyResponseError,
    ParseError,
    QuotaExceededError,
)
from agent.orchestrator import PersonIntelAgent
from agent.schema import DisambiguationResponse, NewsResponse, PersonProfile
from ui.graph_renderer import _build_network
from ui.report_renderer import _apply_filter, _claims_for


class AgentReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.agent = PersonIntelAgent.__new__(PersonIntelAgent)

    def test_configured_output_token_budgets_are_doubled(self):
        self.assertEqual(orchestrator._SEARCHER_MAX_TOKENS, 6000)
        self.assertEqual(orchestrator._WRITER_MAX_TOKENS, 5000)
        self.assertEqual(orchestrator._NEWS_SEARCHER_TOKENS, 8000)
        self.assertEqual(orchestrator._NEWS_WRITER_TOKENS, 6000)
        self.assertEqual(orchestrator._DISAMBIG_TOKENS, 800)
        self.assertEqual(orchestrator._SUMMARY_MAX_TOKENS, 3000)
        self.assertEqual(orchestrator._THINKING_MAX_TOKENS, 16000)
        self.assertEqual(orchestrator._TOKEN_INCREMENT, 2000)

    def test_json_repair_preserves_urls_when_removing_trailing_comma(self):
        repaired = self.agent._repair_json(
            '{"url":"https://example.com/profile",}', "TEST"
        )

        self.assertEqual(repaired, '{"url":"https://example.com/profile"}')

    def test_model_listing_only_exposes_generate_content_models(self):
        models = [
            SimpleNamespace(
                name="models/gemini-supported",
                supported_actions=["generateContent"],
            ),
            SimpleNamespace(
                name="models/gemini-embedding",
                supported_actions=["embedContent"],
            ),
            SimpleNamespace(
                name="models/not-gemini",
                supported_actions=["generateContent"],
            ),
        ]
        client = SimpleNamespace(models=SimpleNamespace(list=Mock(return_value=models)))

        with patch("agent.orchestrator.genai.Client", return_value=client):
            result = PersonIntelAgent.list_models("test-key")

        self.assertEqual(result, ["gemini-supported"])

    def test_json_repair_rejects_javascript_comments_instead_of_mutating_strings(self):
        with self.assertRaises(ParseError):
            self.agent._repair_json(
                '{"url":"https://example.com" // comment\n}', "TEST"
            )

    def test_article_parser_keeps_valid_siblings_around_bad_entries(self):
        articles = self.agent._parse_articles(
            {
                "articles": [
                    {
                        "title": "Valid one",
                        "summary": "Summary",
                        "url": "https://example.com/one",
                    },
                    None,
                    {"title": "Missing URL", "summary": "Summary"},
                    {
                        "title": "Valid two",
                        "summary": "Summary",
                        "url": "http://example.com/two",
                    },
                ]
            },
            "TEST",
        )

        self.assertEqual([article.title for article in articles], ["Valid one", "Valid two"])

    def test_missing_candidates_is_reported_as_empty_response(self):
        response = SimpleNamespace(candidates=None, text=None)

        with self.assertRaises(EmptyResponseError):
            self.agent._extract_text(response, "TEST")

    def test_grounding_metadata_is_preserved_as_searcher_provenance(self):
        response = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    grounding_metadata=SimpleNamespace(
                        grounding_chunks=[
                            SimpleNamespace(
                                web=SimpleNamespace(
                                    title="Official profile",
                                    uri="https://example.go.id/profile",
                                )
                            ),
                            SimpleNamespace(web=None),
                        ]
                    )
                )
            ]
        )

        self.assertEqual(
            self.agent._extract_grounding_sources(response),
            [
                {
                    "title": "Official profile",
                    "url": "https://example.go.id/profile",
                }
            ],
        )

    def test_genai_quota_error_maps_to_quota_exception_without_retry(self):
        self.agent._writer_model = "test-model"
        self.agent._client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=Mock(
                    side_effect=genai_errors.ClientError(
                        429,
                        {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}},
                    )
                )
            )
        )

        with patch("agent.orchestrator.time.sleep", return_value=None):
            with self.assertRaises(QuotaExceededError):
                self.agent._call_writer("prompt", 100, "TEST")

        self.assertEqual(self.agent._client.models.generate_content.call_count, 1)

    def test_parse_error_remains_parse_error_after_writer_retries(self):
        self.agent._writer_model = "test-model"
        self.agent._call_model = Mock(side_effect=ParseError("bad json"))

        with patch("agent.orchestrator.time.sleep", return_value=None):
            with self.assertRaises(ParseError):
                self.agent._call_writer("prompt", 100, "TEST")

        self.assertEqual(self.agent._call_model.call_count, 3)

    def test_thinking_writer_retries_change_the_effective_token_budget(self):
        self.agent._writer_model = "gemini-2.5-pro"
        self.agent._client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=Mock(
                    return_value=SimpleNamespace(candidates=[], text="")
                )
            )
        )

        with patch("agent.orchestrator.time.sleep", return_value=None):
            with self.assertRaises(EmptyResponseError):
                self.agent._call_writer("prompt", 100, "TEST")

        budgets = [
            call.kwargs["config"].max_output_tokens
            for call in self.agent._client.models.generate_content.call_args_list
        ]
        self.assertEqual(budgets, [16000, 18000, 20000])

    def test_structured_tasks_pass_their_pydantic_response_schema(self):
        self.agent._writer_model = "test-model"
        self.agent._call_writer = Mock(return_value='{"candidates": []}')

        self.agent.disambiguate("Example")

        self.assertIs(
            self.agent._call_writer.call_args.kwargs["response_schema"],
            DisambiguationResponse,
        )

        self.agent._call_searcher = Mock(return_value="findings")
        self.agent._call_writer = Mock(return_value='{"articles": []}')
        self.agent.fetch_news("Example")

        self.assertIs(
            self.agent._call_writer.call_args.kwargs["response_schema"],
            NewsResponse,
        )

    def test_profile_source_retrieval_dates_come_from_the_application(self):
        profile, _ = self.agent._parse_profile(
            "Example",
            '{"full_name":"Example","sources":['
            '{"source_id":"S1","url":"https://example.com",'
            '"retrieved_at":"model supplied"}]}'
        )

        self.assertRegex(profile.sources[0].retrieved_at or "", r"^\d{4}-\d{2}-\d{2}$")
        self.assertNotEqual(profile.sources[0].retrieved_at, "model supplied")


class RenderingReliabilityTests(unittest.TestCase):
    def test_dataframe_filter_treats_search_text_as_literal(self):
        frame = pd.DataFrame({"Name": ["PT [Example]", "Other"]})

        filtered = _apply_filter(frame, "[")

        self.assertEqual(filtered["Name"].tolist(), ["PT [Example]"])

    def test_claim_matching_requires_a_nonempty_exact_value(self):
        profile = PersonProfile.model_validate(
            {
                "full_name": "Example",
                "current_roles": ["Minister"],
                "sources": [
                    {"source_id": "S1", "url": "https://example.com/one"},
                    {"source_id": "S2", "url": "https://example.com/two"},
                ],
                "claims": [
                    {"field": "current_roles", "value": "", "evidence_ids": ["S1"]},
                    {
                        "field": "current_roles",
                        "value": "Minister for Energy",
                        "evidence_ids": ["S2"],
                    },
                ],
            }
        )

        self.assertEqual(_claims_for(profile, "current_roles", "Minister"), [])

    def test_graph_tooltip_escapes_profile_content(self):
        profile = PersonProfile(
            full_name='<img src=x onerror="alert(1)">',
            party_affiliations=["Party & Group"],
        )

        network = _build_network(profile)

        self.assertNotIn("<img", network.nodes[0]["title"])
        self.assertIn("&lt;img", network.nodes[0]["title"])


if __name__ == "__main__":
    unittest.main()
