import unittest
from forgeapp.semver import bump, compare, parse


class SemverTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse("v1.2.3"), (1, 2, 3))

    def test_bump_minor_resets_patch(self):
        self.assertEqual(bump("1.4.9", "minor"), "1.5.0")

    def test_bump_major(self):
        self.assertEqual(bump("1.4.9", "major"), "2.0.0")

    def test_compare_numeric_not_lexical(self):
        self.assertEqual(compare("1.10.0", "1.9.0"), 1)
