import unittest
from forgeapp.pipeline_lint import lint_stages


class PipelineLintTests(unittest.TestCase):
    def test_valid(self):
        stages = [{"name": "build"}, {"name": "test"}, {"name": "deploy", "approval": "required"}]
        self.assertEqual(lint_stages(stages), [])

    def test_deploy_before_test(self):
        stages = [{"name": "deploy", "approval": "required"}, {"name": "test"}]
        self.assertIn("deploy runs before test", lint_stages(stages))

    def test_missing_approval(self):
        stages = [{"name": "test"}, {"name": "deploy"}]
        self.assertIn("deploy stage must require approval", lint_stages(stages))
