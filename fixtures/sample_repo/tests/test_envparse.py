import unittest
from forgeapp.envparse import parse_env_line


class EnvParseTests(unittest.TestCase):
    def test_quoted(self):
        self.assertEqual(parse_env_line('TOKEN="a=b"'), ("TOKEN", "a=b"))

    def test_comment(self):
        self.assertIsNone(parse_env_line("# note"))
