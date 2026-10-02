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

    def test_initial_and_more_search_use_25_top_ranks_and_5_exploration_releases(self):
        for release_id in range(4, 103):
            self.releases[release_id] = Release(
                id=release_id, title=f"Release {release_id}", artists=["Artist"],
                labels=["Label"], genres=["Electronic"], styles=["House"], year=2000,
            )
            listing = {
                "id": 100 + release_id, "release": {"id": release_id, "artist": "Artist"},
                "price": {"value": 10, "currency": "EUR"}, "condition": "Mint (M)",
            }
            self.inventory["listings"].extend([listing, {**listing, "id": 1000 + release_id}])

        first = [json.loads(line) for line in service.recommend_stream("user", "seller")]
        first_ids = [event["recommendation"]["release_id"] for event in first
                     if event["type"] == "recommendation"]
        self.assertEqual(first_ids, list(range(3, 28)) + [35, 50, 65, 80, 95])
        self.assertTrue(first[-1]["has_more"])
        self.assertEqual(first[-1]["next_inventory_page_limit"], 10)
        regular = service.recommend("user", "seller")["recommendations"]
        self.assertEqual({item["release_id"] for item in regular}, set(first_ids))

        second = [json.loads(line) for line in service.recommend_stream(
            "user", "seller", exclude_release_ids=first_ids + [2],
        )]
        second_ids = [event["recommendation"]["release_id"] for event in second
                      if event["type"] == "recommendation"]
        expected_top = [release_id for release_id in range(28, 55) if release_id not in (35, 50)]
        self.assertEqual(second_ids, expected_top + [59, 69, 78, 88, 98])
        self.assertFalse(set(first_ids) & set(second_ids))
        self.assertTrue(second[-1]["has_more"])

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
        self.assertEqual(events[-1], {
            "type": "done", "recommendations": 1, "wantlist_matches": 1,
            "has_more": False, "next_inventory_page_limit": 1,
        })

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

    def test_more_batches_skip_shown_releases_and_stop_at_exhaustion(self):
        for release_id in range(4, 36):
            self.releases[release_id] = Release(
                id=release_id, title=f"Release {release_id}", artists=["Artist"],
                labels=["Label"], genres=["Electronic"], styles=["House"], year=2000,
            )
            self.inventory["listings"].append({
                "id": 100 + release_id, "release": {"id": release_id, "artist": "Artist"},
                "price": {"value": 10, "currency": "EUR"}, "condition": "Mint (M)",
            })
        first = [json.loads(line) for line in service.recommend_stream("user", "seller")]
        shown = [event["recommendation"]["release_id"] for event in first
                 if event["type"] in ("recommendation", "wantlist")]
        self.assertEqual(first[-1]["recommendations"], 30)
        self.assertTrue(first[-1]["has_more"])
        self.assertEqual(first[-1]["next_inventory_page_limit"], 10)
        with patch.object(service, "link_listing", wraps=service.link_listing) as link:
            second = [json.loads(line) for line in service.recommend_stream(
                "user", "seller", exclude_release_ids=shown,
                inventory_page_limit=first[-1]["next_inventory_page_limit"],
            )]
        more = [event["recommendation"]["release_id"] for event in second
                if event["type"] == "recommendation"]
        self.assertEqual(len(more), 3)
        self.assertFalse(set(shown) & set(more))
        self.assertEqual(link.call_count, 3)
        self.assertFalse(second[-1]["has_more"])

    def test_more_search_expands_inventory_after_current_candidates_are_exhausted(self):
        first_page = {**self.inventory, "pagination": {"pages": 11}}
        later_page = {
            "pagination": {"pages": 11},
            "listings": [{
                "id": 99, "release": {"id": 4, "artist": "Artist"},
                "price": {"value": 10, "currency": "EUR"}, "condition": "Mint (M)",
            }],
        }
        self.releases[4] = Release(
            id=4, title="Later record", artists=["Artist"], labels=["Label"],
            genres=["Electronic"], styles=["House"], year=2000,
        )
        def inventory(*args, page=1, **kwargs):
            if page == 1:
                return first_page
            if page == 11:
                return later_page
            return {"pagination": {"pages": 11}, "listings": []}
        with patch.object(service, "get_inventory_raw", side_effect=inventory) as fetch:
            first = [json.loads(line) for line in service.recommend_stream("user", "seller")]
            self.assertTrue(first[-1]["has_more"])
            self.assertEqual(first[-1]["next_inventory_page_limit"], 11)
            second = [json.loads(line) for line in service.recommend_stream(
                "user", "seller", exclude_release_ids=[2, 3], inventory_page_limit=11,
            )]
        results = [event["recommendation"] for event in second if event["type"] == "recommendation"]
        self.assertEqual([item["release_id"] for item in results], [4])
        self.assertFalse(second[-1]["has_more"])
        self.assertIn(11, [call.kwargs["page"] for call in fetch.call_args_list])

    def test_failed_batch_can_continue_without_loading_completed_releases_again(self):
        original_link = service.link_listing
        def link(listing):
            if listing.release_id == 3:
                raise ValueError("Temporary failure")
            return original_link(listing)
        with patch.object(service, "link_listing", side_effect=link):
            failed = [json.loads(line) for line in service.recommend_stream("user", "seller")]
        self.assertEqual(failed[-1]["type"], "error")
        retried = [json.loads(line) for line in service.recommend_stream(
            "user", "seller", exclude_release_ids=[2],
        )]
        self.assertFalse(any(event["type"] == "wantlist" for event in retried))
        self.assertEqual(retried[-1]["recommendations"], 1)
