import os
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from agent.schema import DisambiguationCandidate, PersonProfile


class AppFlowTests(unittest.TestCase):
    def test_server_api_key_is_not_copied_into_the_password_widget(self):
        with (
            patch.dict(os.environ, {"GOOGLE_API_KEY": "server-secret"}),
            patch(
                "agent.orchestrator.PersonIntelAgent.list_models",
                return_value=["test-model"],
            ) as list_models,
        ):
            app = AppTest.from_file("app.py").run(timeout=15)

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.text_input(key="api_key_input").value, "")
        list_models.assert_called_with("server-secret")

    def test_repeated_unambiguous_search_uses_cache_before_disambiguation(self):
        profile = PersonProfile(full_name="Review Fixture")
        with (
            patch.dict(os.environ, {"GOOGLE_API_KEY": ""}),
            patch("agent.orchestrator.PersonIntelAgent.__init__", return_value=None),
            patch(
                "agent.orchestrator.PersonIntelAgent.list_models",
                return_value=["test-model"],
            ),
            patch(
                "agent.orchestrator.PersonIntelAgent.disambiguate", return_value=[]
            ) as disambiguate,
            patch(
                "agent.orchestrator.PersonIntelAgent.run",
                return_value=(profile, "{}"),
            ) as run,
        ):
            app = AppTest.from_file("app.py").run(timeout=15)
            app.text_input(key="api_key_input").input("user-key").run(timeout=15)
            search = next(
                widget
                for widget in app.text_input
                if widget.label == "Nama tokoh"
            )
            search.input("Review Fixture")
            next(
                button for button in app.button if "Telusuri tokoh" in button.label
            ).click().run(timeout=15)
            next(
                button for button in app.button if "Telusuri tokoh" in button.label
            ).click().run(timeout=15)

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(disambiguate.call_count, 1)
        self.assertEqual(run.call_count, 1)

    def test_disambiguation_context_is_included_in_the_research_query(self):
        profile = PersonProfile(full_name="Alex Example")
        candidates = [
            DisambiguationCandidate(
                name="Alex Example", description="Mayor of North"
            ),
            DisambiguationCandidate(
                name="Alex Example", description="Mayor of South"
            ),
        ]
        with (
            patch.dict(os.environ, {"GOOGLE_API_KEY": ""}),
            patch("agent.orchestrator.PersonIntelAgent.__init__", return_value=None),
            patch(
                "agent.orchestrator.PersonIntelAgent.list_models",
                return_value=["test-model"],
            ),
            patch(
                "agent.orchestrator.PersonIntelAgent.disambiguate",
                return_value=candidates,
            ),
            patch(
                "agent.orchestrator.PersonIntelAgent.run",
                return_value=(profile, "{}"),
            ) as run,
        ):
            app = AppTest.from_file("app.py").run(timeout=15)
            app.text_input(key="api_key_input").input("user-key").run(timeout=15)
            search = next(
                widget
                for widget in app.text_input
                if widget.label == "Nama tokoh"
            )
            search.input("Alex Example")
            next(
                button for button in app.button if "Telusuri tokoh" in button.label
            ).click().run(timeout=15)
            app.radio(key="disambiguation").set_value(
                "Alex Example: Mayor of North"
            )
            app.button(key="disambig_confirm").click().run(timeout=15)

        self.assertEqual(len(app.exception), 0)
        researched_query = run.call_args.args[0]
        self.assertIn("Mayor of North", researched_query)


if __name__ == "__main__":
    unittest.main()
