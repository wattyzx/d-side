import unittest

from app.seller_input import normalize_seller


class SellerInputTests(unittest.TestCase):
    def test_names_and_supported_links(self):
        for value in (
            "  Some.Shop-1  ",
            "https://www.discogs.com/seller/Some.Shop-1/profile",
            "https://www.discogs.com/seller/Some.Shop-1/shop?sort=price&limit=250",
            "discogs.com/user/Some.Shop-1/",
            "https://www.discogs.com/en/seller/Some.Shop-1/profile",
            "https://www.discogs.com/sell/list?seller=Some.Shop-1",
        ):
            with self.subTest(value=value):
                self.assertEqual(normalize_seller(value), "Some.Shop-1")

    def test_unrelated_urls_and_path_injection_are_rejected(self):
        for value in (
            "", "  ", "a/b", "name?x=y", "a b", "discogs.com", ".", "..",
            "https://discogs.com.evil.example/seller/name/profile",
            "https://evil.example/seller/name/profile",
            "https://name@discogs.com/user/name",
            "https://www.discogs.com/release/123",
            "https://www.discogs.com/sell/item/123",
            "https://www.discogs.com/user/a%2Fb",
            "https://www.discogs.com/user/%2E%2E",
            "https://www.discogs.com/sell/list?seller=a&seller=b",
            "https://www.discogs.com:bad/user/name",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_seller(value)
