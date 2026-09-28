import unittest
from forgeapp.slugify import slugify


class SlugifyTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Release Notes: v2.1!"), "release-notes-v2-1")

    def test_trim(self):
        self.assertEqual(slugify("  --Hello World--  "), "hello-world")
