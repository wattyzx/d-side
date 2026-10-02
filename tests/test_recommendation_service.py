import json
import unittest
from unittest.mock import patch

from app.models.inventory_item import InventoryItem
from app.models.release import Release
from app.services import recommendation_service as service
from app.services.release_mapper import inventory_to_listings


class RecommendationServiceTests(unittest.TestCase):
    def setUp(self):
        self.releases = {
            release_id: Release(
                id=release_id,
                title=f"Release {release_id}",
                artists=["Artist"],
                labels=["Label"],
                genres=["Electronic"],
                styles=["House"],
                year=2000,
            )
            for release_id in (1, 2, 3)
        }
        self.inventory = {
            "pagination": {"pages": 1},
            "listings": [
                {
                    "id": listing_id,
                    "release": {"id": release_id, "artist": "Artist"},
                    "price": {"value": 10.0, "currency": "EUR"},
                    "condition": "Near Mint (NM or M-)",
                }
                for listing_id, release_id in ((11, 1), (12, 2), (13, 2), (14, 3))
            ],
        }

        def link(listing):
            return InventoryItem(listing=listing, release=self.releases[listing.release_id])

        mocks = patch.multiple(
            service,
            get_collection=lambda _: [self.releases[1]],
            get_wantlist_ids=lambda _: [1, 2],
            get_inventory_raw=lambda *args, **kwargs: self.inventory,
            get_inventory=lambda *args, **kwargs: inventory_to_listings(self.inventory),
            link_listing=link,
            link_inventory=lambda listings: [link(listing) for listing in listings],
        )
        mocks.start()
        self.addCleanup(mocks.stop)

    def test_regular_endpoint_scores_recommendations(self):
        result = service.recommend("user", "seller")
        self.assertEqual(len(result["recommendations"]), 1)
        self.assertEqual(result["recommendations"][0]["release_id"], 3)
        self.assertGreater(result["recommendations"][0]["score"], 0)

    def test_stream_payloads_match_frontend_contract(self):
        events = [json.loads(line) for line in service.recommend_stream("user", "seller")]
        self.assertFalse(any(event["type"] == "error" for event in events))
        recommendations = [
            event["recommendation"] for event in events if event["type"] == "recommendation"
        ]
        self.assertEqual(recommendations, service.recommend("user", "seller")["recommendations"])
        wantlist = [event["recommendation"] for event in events if event["type"] == "wantlist"]
        self.assertEqual(len(wantlist), 1)
        self.assertEqual(wantlist[0]["release_id"], 2)
        self.assertEqual(wantlist[0]["title"], "Release 2")
        self.assertEqual(wantlist[0]["artists"], ["Artist"])
        self.assertEqual(wantlist[0]["labels"], ["Label"])
        self.assertEqual(wantlist[0]["styles"], ["House"])
        self.assertEqual(wantlist[0]["price"], 10.0)
        self.assertIsNone(wantlist[0]["sleeve_condition"])
        self.assertEqual(events[-1], {"type": "done", "recommendations": 1, "wantlist_matches": 1})

    def test_stream_reports_upstream_errors(self):
        with patch.object(service, "get_collection", side_effect=ValueError("No collection")):
            events = [json.loads(line) for line in service.recommend_stream("user", "seller")]
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["message"], "No collection")

    def test_stream_scores_each_candidate_before_loading_the_next(self):
        self.releases[4] = Release(
            id=4, title="Release 4", artists=["Artist"], labels=["Label"],
            genres=["Electronic"], styles=["House"], year=2000,
        )
        self.inventory["listings"].append({
            "id": 15, "release": {"id": 4, "artist": "Artist"},
            "price": {"value": 12.0, "currency": "EUR"},
            "condition": "Near Mint (NM or M-)",
        })
        original_link = service.link_listing
        loaded = []

        def track_link(listing):
            loaded.append(listing.release_id)
            return original_link(listing)

        with patch.object(service, "link_listing", side_effect=track_link):
            stream = service.recommend_stream("user", "seller")
            first = next(
                event for line in stream
                if (event := json.loads(line))["type"] == "recommendation"
            )
            self.assertEqual(loaded, [2, 3])
            self.assertEqual(first["recommendation"]["release_id"], 3)
            self.assertEqual(first["processed"], 1)
            self.assertEqual(first["candidates"], 2)
            remaining = [json.loads(line) for line in stream]

        self.assertEqual(loaded, [2, 3, 4])
        self.assertEqual(remaining[0]["type"], "recommendation")
        self.assertEqual(remaining[0]["processed"], 2)
        self.assertEqual(remaining[-1]["recommendations"], 2)

    def test_stream_matches_regular_scores_after_sorting(self):
        self.releases[4] = Release(
            id=4, title="Release 4", artists=["Artist"], labels=["Label"],
            genres=["Electronic"], styles=["House"], year=2000,
        )
        self.releases[3].styles = ["Techno"]
        self.inventory["listings"].append({
            "id": 15, "release": {"id": 4, "artist": "Artist"},
            "price": {"value": 12.0, "currency": "EUR"},
            "condition": "Near Mint (NM or M-)",
        })
        events = [json.loads(line) for line in service.recommend_stream("user", "seller")]
        results = [event["recommendation"] for event in events if event["type"] == "recommendation"]
        self.assertEqual([result["release_id"] for result in results], [3, 4])
        results.sort(key=lambda result: result["score_breakdown"]["total"], reverse=True)
        self.assertEqual(results, service.recommend("user", "seller")["recommendations"])
