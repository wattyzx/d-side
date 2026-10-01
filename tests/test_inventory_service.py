import unittest

from app.services.inventory_service import choose_inventory_pages


class InventorySamplingTests(unittest.TestCase):

    def test_stratified_sampling(self):
        self.assertEqual(
            choose_inventory_pages(44, 10),
            [1, 6, 11, 15, 20, 25, 30, 34, 39, 44],
        )

    def test_sample_larger_than_inventory_returns_all_pages(self):
        self.assertEqual(
            choose_inventory_pages(5, 10),
            [1, 2, 3, 4, 5],
        )

    def test_single_page_sample(self):
        self.assertEqual(
            choose_inventory_pages(44, 1),
            [1],
        )

    def test_invalid_values(self):
        self.assertEqual(choose_inventory_pages(0, 10), [])
        self.assertEqual(choose_inventory_pages(10, 0), [])