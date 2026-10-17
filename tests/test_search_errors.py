import unittest

import httpx

from app.search_errors import search_error_message
from app.services.database import DatabaseError


class SearchErrorTests(unittest.TestCase):
    def test_http_errors_have_actions_without_exposing_upstream_details(self):
        for status, expected in ((401, "Sign out"), (403, "Sign out"),
                                 (429, "Wait a minute"), (404, "seller name"),
                                 (503, "temporarily unavailable")):
            with self.subTest(status=status):
                request = httpx.Request("GET", "https://api.discogs.com/private-example")
                error = httpx.HTTPStatusError("internal diagnostic", request=request,
                                             response=httpx.Response(status, request=request))
                message = search_error_message(error)
                self.assertIn(expected, message)
                self.assertNotIn("internal diagnostic", message)
                self.assertNotIn("https://", message)

    def test_transport_database_and_unexpected_errors_are_readable(self):
        for error, expected in (
            (httpx.ReadTimeout("internal diagnostic"), "too long"),
            (httpx.ConnectError("internal diagnostic"), "connect to Discogs"),
            (DatabaseError("internal diagnostic"), "Saved data"),
            (ValueError("internal diagnostic"), "results already found are kept"),
        ):
            with self.subTest(error=type(error).__name__):
                message = search_error_message(error)
                self.assertIn(expected, message)
                self.assertNotIn("internal diagnostic", message)
