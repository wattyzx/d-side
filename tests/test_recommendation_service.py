import json
import unittest
from unittest.mock import patch

from app.models.inventory_item import InventoryItem
from app.models.release import Release
from app.services import recommendation_service as service
from app.services import recommender
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
        self.assertEqual(first[-1]["next_inventory_page_limit"], 1)
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
            "inventory_truncated": False,
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
            self.assertEqual(loaded, [3])
            self.assertEqual(first["recommendation"]["release_id"], 3)
            self.assertEqual(first["processed"], 1)
            self.assertEqual(first["candidates"], 2)
            remaining = [json.loads(line) for line in stream]

        self.assertEqual(loaded, [3, 4, 2])
        self.assertEqual(remaining[0]["type"], "recommendation")
        self.assertEqual(remaining[0]["processed"], 2)
        self.assertEqual(remaining[-1]["recommendations"], 2)

    def test_first_recommendation_does_not_wait_for_wants_or_later_pages(self):
        first_page = {**self.inventory, "pagination": {"pages": 100}}
        original_link = service.link_listing
        with patch.object(service, "get_inventory_raw", return_value=first_page) as fetch, \
                patch.object(service, "link_listing", wraps=original_link) as link:
            stream = service.recommend_stream("user", "seller")
            events = []
            for line in stream:
                event = json.loads(line)
                events.append(event)
                if event["type"] == "recommendation":
                    break
            self.assertEqual(events[-1]["type"], "recommendation")
            self.assertEqual(events[-1]["recommendation"]["release_id"], 3)
            self.assertTrue(events[-1]["inventory_scanning"])
            self.assertEqual([call.kwargs["page"] for call in fetch.call_args_list], [1])
            self.assertEqual([call.args[0].release_id for call in link.call_args_list], [3])
            self.assertFalse(any(event["type"] in ("wantlist", "inventory_complete")
                                 for event in events))
            stream.close()

    def test_empty_early_pages_keep_budget_for_late_candidates(self):
        for release_id in range(4, 43):
            self.releases[release_id] = Release(
                id=release_id, title=f"Release {release_id}", artists=["Artist"],
                labels=["Label"], genres=["Electronic"], styles=["House"], year=2000,
            )
            self.inventory["listings"].append({
                "id": 100 + release_id, "release": {"id": release_id, "artist": "Artist"},
                "price": {"value": 10, "currency": "EUR"}, "condition": "Mint (M)",
            })

        def inventory(*args, page=1, **kwargs):
            return {
                "pagination": {"pages": 3},
                "listings": self.inventory["listings"] if page == 3 else [],
            }

        with patch.object(service, "get_inventory_raw", side_effect=inventory):
            events = [json.loads(line) for line in service.recommend_stream("user", "seller")]
        ids = [event["recommendation"]["release_id"] for event in events
               if event["type"] == "recommendation"]
        self.assertEqual(len(ids), 30)
        self.assertEqual(len(set(ids)), 30)
        self.assertEqual(ids[:25], list(range(3, 28)))
        self.assertTrue(events[-1]["has_more"])

    def test_long_scan_prepares_preferences_once_and_scores_only_new_listings(self):
        def inventory(*args, page=1, **kwargs):
            release_id = 100 + page
            self.releases[release_id] = Release(release_id, f"Release {release_id}", styles=["House"])
            return {"pagination": {"pages": 100}, "listings": [{
                "id": page, "release": {"id": release_id, "artist": "Artist"},
                "price": {"value": 10, "currency": "EUR"}, "condition": "Mint (M)",
            }]}
        with patch.object(service, "get_inventory_raw", side_effect=inventory), \
             patch.object(recommender, "_normalized_preferences", wraps=recommender._normalized_preferences) as prepare, \
             patch.object(recommender, "pre_score_listing", wraps=recommender.pre_score_listing) as score:
            events = [json.loads(line) for line in service.recommend_stream("user", "seller")]
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["recommendations"], 30)
        self.assertEqual(score.call_count, 100)
        self.assertEqual(prepare.call_count, 4)  # Artist, label, style, and genre lookups.

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
        self.assertEqual(first[-1]["next_inventory_page_limit"], 1)
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

    def test_large_inventory_finds_late_wants_and_scores_all_pages_across_batches(self):
        pages = {}
        for page in range(1, 45):
            release_id = 100 + page
            self.releases[release_id] = Release(
                id=release_id, title=f"Release {release_id}", artists=["Artist"],
                labels=["Label"], genres=["Electronic"], styles=["House"], year=2000,
            )
            pages[page] = {
                "pagination": {"pages": 44},
                "listings": [{
                    "id": 1000 + page,
                    "release": {"id": release_id, "artist": "Artist"},
                    "price": {"value": 10, "currency": "EUR"},
                    "condition": "Mint (M)",
                }],
            }
        # A second copy of an early want, plus an owned record on the last page.
        pages[44]["listings"].extend([
            pages[11]["listings"][0], self.inventory["listings"][0],
        ])

        def inventory(*args, page=1, **kwargs):
            return pages[page]

        with patch.object(service, "get_inventory_raw", side_effect=inventory) as fetch, \
                patch.object(service, "get_wantlist_ids", return_value={1, 111, 144}):
            # Even legacy clients sending a ten-page limit must get the full scan.
            first = [json.loads(line) for line in service.recommend_stream(
                "user", "seller", inventory_page_limit=10, exclude_release_ids=[132],
            )]
            self.assertEqual([call.kwargs["page"] for call in fetch.call_args_list],
                             list(range(1, 45)))
            wants = [event["recommendation"]["release_id"] for event in first
                     if event["type"] == "wantlist"]
            self.assertEqual(wants, [111, 144])
            progress = [event for event in first if event["type"] == "progress"]
            self.assertEqual(len(progress), 44)
            self.assertEqual(progress[-1]["pages"], 44)
            first_ids = [event["recommendation"]["release_id"] for event in first
                         if event["type"] == "recommendation"]
            self.assertEqual(len(first_ids), 30)
            self.assertTrue(first[-1]["has_more"])

            second = [json.loads(line) for line in service.recommend_stream(
                "user", "seller", exclude_release_ids=first_ids + wants + [132],
            )]
            second_ids = [event["recommendation"]["release_id"] for event in second
                          if event["type"] == "recommendation"]
            self.assertFalse(set(first_ids) & set(second_ids))
            self.assertEqual(set(first_ids + second_ids),
                             set(range(101, 145)) - {111, 132, 144})
            self.assertFalse(any(event["type"] == "wantlist" for event in second))
            self.assertFalse(second[-1]["has_more"])

    def test_regular_endpoint_ranks_the_complete_large_inventory(self):
        with patch.object(service, "get_inventory_raw", return_value={
            "pagination": {"pages": 44}, "listings": [],
        }), patch.object(service, "get_inventory", return_value=[]) as fetch:
            result = service.recommend("user", "seller")
        self.assertEqual(fetch.call_args.kwargs["pages"], list(range(1, 45)))
        self.assertEqual(result["sample_pages"], list(range(1, 45)))
        self.assertEqual(result["recommendations"], [])

    def test_api_page_ceiling_preserves_results_and_reports_incomplete_coverage(self):
        self.releases[4] = Release(
            id=4, title="Want on page 100", artists=["Artist"], labels=["Label"],
            genres=["Electronic"], styles=["House"], year=2000,
        )

        def inventory(*args, page=1, **kwargs):
            if page > 100:
                self.fail("Discogs rejects this request with HTTP 403")
            if page == 1:
                return {**self.inventory, "pagination": {"pages": 137}}
            return {
                "pagination": {"pages": 137},
                "listings": [{
                    "id": 1004, "release": {"id": 4, "artist": "Artist"},
                    "price": {"value": 10, "currency": "EUR"},
                    "condition": "Mint (M)",
                }] if page == 100 else [],
            }

        with patch.object(service, "get_inventory_raw", side_effect=inventory) as fetch, \
                patch.object(service, "get_wantlist_ids", return_value={2, 4}):
            events = [json.loads(line) for line in service.recommend_stream("user", "seller")]
            self.assertEqual([call.kwargs["page"] for call in fetch.call_args_list],
                             list(range(1, 101)))
            start = next(event for event in events if event["type"] == "start")
            self.assertEqual(start["reported_pages"], 137)
            self.assertEqual(start["sample_pages"], list(range(1, 101)))
            self.assertTrue(start["inventory_truncated"])
            self.assertEqual([event["recommendation"]["release_id"] for event in events
                              if event["type"] == "wantlist"], [2, 4])
            self.assertEqual([event["recommendation"]["release_id"] for event in events
                              if event["type"] == "recommendation"], [3])
            self.assertEqual(events[-1]["type"], "done")
            self.assertTrue(events[-1]["inventory_truncated"])
            # No further accessible candidates; never suggest page 101.
            self.assertFalse(events[-1]["has_more"])
            self.assertEqual(events[-1]["next_inventory_page_limit"], 100)

    def test_regular_endpoint_respects_api_page_ceiling(self):
        with patch.object(service, "get_inventory_raw", return_value={
            "pagination": {"pages": 137}, "listings": [],
        }), patch.object(service, "get_inventory", return_value=[]) as fetch:
            result = service.recommend("user", "seller")
        self.assertEqual(fetch.call_args.kwargs["pages"], list(range(1, 101)))
        self.assertEqual(result["reported_pages"], 137)
        self.assertTrue(result["inventory_truncated"])

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
