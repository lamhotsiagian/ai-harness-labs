import unittest
from forgeapp.inventory import OutOfStock, reserve


class InventoryTests(unittest.TestCase):
    def test_reserve(self):
        self.assertEqual(reserve({"a": 5}, "a", 2), {"a": 3})

    def test_exact_quantity_allowed(self):
        self.assertEqual(reserve({"a": 2}, "a", 2), {"a": 0})

    def test_no_mutation(self):
        stock = {"a": 5}
        reserve(stock, "a", 1)
        self.assertEqual(stock, {"a": 5})

    def test_out_of_stock(self):
        with self.assertRaises(OutOfStock):
            reserve({"a": 1}, "a", 2)
