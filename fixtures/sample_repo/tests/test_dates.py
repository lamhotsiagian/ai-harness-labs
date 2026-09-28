import unittest
from datetime import date
from forgeapp.dates import business_days_between, is_weekend


class DatesTests(unittest.TestCase):
    def test_weekend(self):
        self.assertTrue(is_weekend(date(2026, 9, 26)))

    def test_business_days(self):
        self.assertEqual(business_days_between(date(2026, 9, 21), date(2026, 9, 28)), 5)
