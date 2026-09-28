import unittest
from forgeapp.textstats import top_words, word_count


class TextStatsTests(unittest.TestCase):
    def test_count(self):
        self.assertEqual(word_count("Fix the build, don't break it"), 6)

    def test_top_words_tiebreak(self):
        self.assertEqual(top_words("b a b a c", 2), ["a", "b"])
