import unittest
from unittest.mock import patch

from agent.exceptions import EmptyResponseError
from agent.orchestrator import PersonIntelAgent
from agent.prompts import build_news_writer_prompt, build_writer_prompt
from agent.schema import PersonProfile
from ui.components import badge
from ui.news_renderer import _safe_http_url
from ui.report_renderer import _claim_sources_html, render_summary


class AgentContractTests(unittest.TestCase):
    def test_writer_retry_raises_empty_response_not_name_error(self):
        agent = PersonIntelAgent.__new__(PersonIntelAgent)
        agent._writer_model = "test-model"
        calls = []

        def fake_call_model(**kwargs):
            calls.append(kwargs)
            raise EmptyResponseError("empty")

        agent._call_model = fake_call_model

        with patch("agent.orchestrator.time.sleep", return_value=None):
            with self.assertRaises(EmptyResponseError):
                agent._call_writer("prompt", 10, "TEST")

        self.assertEqual(len(calls), 3)
        self.assertEqual([call["max_tokens"] for call in calls], [10, 1010, 2010])
        self.assertGreater(calls[-1]["temperature"], calls[0]["temperature"])

    def test_news_empty_result_contract_uses_articles_object(self):
        prompt = build_news_writer_prompt("Nama Tokoh", "Tidak ada artikel")

        self.assertIn('{"articles": []}', prompt)
        self.assertNotIn("array kosong: []", prompt)

    def test_profile_writer_prompt_includes_evidence_contract(self):
        prompt = build_writer_prompt("Nama Tokoh", "Sumber: https://example.com")

        self.assertIn('"source_id": "S1"', prompt)
        self.assertIn('"claims": [', prompt)
        self.assertIn('"evidence_ids": ["S1"]', prompt)
        self.assertIn("current_roles", prompt)
        self.assertIn("corporate_affiliations", prompt)


class EvidenceSchemaTests(unittest.TestCase):
    def test_profile_accepts_source_ids_and_claims(self):
        profile = PersonProfile.model_validate({
            "full_name": "Nama Tokoh",
            "current_roles": ["Menteri Contoh"],
            "sources": [
                {
                    "source_id": "S1",
                    "url": "https://example.com/profile",
                    "title": "Profil Resmi",
                    "quality": "official",
                    "retrieved_at": "2026-06-24",
                    "snippet": "Menjabat sebagai Menteri Contoh.",
                }
            ],
            "claims": [
                {
                    "claim_id": "C1",
                    "dimension": "jabatan",
                    "field": "current_roles",
                    "value": "Menteri Contoh",
                    "evidence_ids": ["S1"],
                    "confidence": "high",
                }
            ],
        })

        self.assertEqual(profile.sources[0].source_id, "S1")
        self.assertEqual(profile.sources[0].quality.value, "Resmi")
        self.assertEqual(profile.sources[0].retrieved_at, "2026-06-24")
        self.assertEqual(profile.claims[0].evidence_ids, ["S1"])

    def test_claim_sources_html_links_matching_role_to_source(self):
        profile = PersonProfile.model_validate({
            "full_name": "Nama Tokoh",
            "current_roles": ["Menteri Contoh"],
            "sources": [
                {
                    "source_id": "S1",
                    "url": "https://example.com/profile",
                    "title": "Profil Resmi",
                    "quality": "Resmi",
                    "retrieved_at": "2026-06-24",
                    "snippet": "Menjabat sebagai Menteri Contoh.",
                }
            ],
            "claims": [
                {
                    "dimension": "jabatan",
                    "field": "current_roles",
                    "value": "Menteri Contoh",
                    "evidence_ids": ["S1"],
                }
            ],
        })

        html = _claim_sources_html(profile, "current_roles", "Menteri Contoh")

        self.assertIn('href="https://example.com/profile"', html)
        self.assertIn("Profil Resmi", html)
        self.assertIn("2026-06-24", html)


class RenderingSafetyTests(unittest.TestCase):
    def test_badge_escapes_html_text(self):
        html = badge("<script>alert(1)</script>", "#fff")

        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)

    def test_render_summary_escapes_html(self):
        with patch("ui.report_renderer.st.markdown") as markdown:
            render_summary("<b>bold</b>\nsecond paragraph")

        rendered = markdown.call_args.args[0]
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;", rendered)
        self.assertNotIn("<b>bold</b>", rendered)

    def test_safe_http_url_rejects_unsafe_schemes(self):
        self.assertEqual(_safe_http_url("javascript:alert(1)"), "")
        self.assertEqual(_safe_http_url("data:text/html,hello"), "")
        self.assertEqual(_safe_http_url("not-a-url"), "")
        self.assertEqual(_safe_http_url("https://example.com/news"), "https://example.com/news")


if __name__ == "__main__":
    unittest.main()
