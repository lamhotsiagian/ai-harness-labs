"""Headless UI test for the Streamlit companion app (skipped when streamlit is not installed)."""
import unittest
from pathlib import Path

APP = str(Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py")

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None


@unittest.skipIf(AppTest is None, "pip install streamlit")
class UITests(unittest.TestCase):
    def test_agent_run_and_approval_flow(self):
        at = AppTest.from_file(APP, default_timeout=180).run()
        self.assertFalse(at.exception)
        at.sidebar.radio[0].set_value("Agent run").run()
        at.button[0].click().run()
        self.assertIn("success (hidden tests)", [m.label for m in at.metric])
        at.sidebar.radio[0].set_value("Approvals").run()
        at.button[0].click().run()                         # agent proposes "Add a lint stage before test"
        [b for b in at.button if b.label == "Approve"][0].click().run()
        self.assertIn("name: lint", at.code[-1].value)      # applied only after a human approved


if __name__ == "__main__":
    unittest.main()
