import unittest
from forgeapp.pricing import apply_discount, total_with_tax


class PricingTests(unittest.TestCase):
    def test_discount(self):
        self.assertEqual(apply_discount(200.0, 25), 150.0)

    def test_discount_bounds(self):
        with self.assertRaises(ValueError):
            apply_discount(10.0, 120)

    def test_tax(self):
        self.assertEqual(total_with_tax([10.0, 20.0], 0.1), 33.0)


if __name__ == "__main__":
    unittest.main()
