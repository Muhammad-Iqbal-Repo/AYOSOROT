import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from google.genai import types

from agent.orchestrator import PersonIntelAgent, _WRITER_INPUT_MAX_TOKENS
from agent.prompts import build_searcher_prompt, build_writer_prompt


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
        writer_prompt = self.agent._call_writer.call_args.kwargs["prompt"]
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

    def test_search_prompt_requires_identity_and_source_selection(self):
        prompt = build_searcher_prompt("Alex Example: Mayor of North", ["jabatan"])
        self.assertIn("Mayor of North", prompt)
        self.assertIn("orang yang sama", prompt)
        self.assertIn("URL", prompt)

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


if __name__ == "__main__":
    unittest.main()
