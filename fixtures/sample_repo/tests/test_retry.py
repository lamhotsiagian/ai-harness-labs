import unittest
from forgeapp.retry import backoff_delays


class RetryTests(unittest.TestCase):
    def test_schedule(self):
        self.assertEqual(backoff_delays(1.0, 2.0, 4, 100.0), [1.0, 2.0, 4.0, 8.0])

    def test_cap(self):
        self.assertEqual(backoff_delays(1.0, 10.0, 3, 50.0), [1.0, 10.0, 50.0])
