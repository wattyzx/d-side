import json
from math import ceil

from app.services.discogs_client import (
    get_collection,
    get_inventory,
    get_inventory_raw,
    get_wantlist_ids,
)
from app.services.release_mapper import inventory_to_listings
from app.services.recommender import (
    ListingRanker,
    prepare_taste,
    rank_inventory_items,
    rank_listings,
    select_candidates,
    select_progressive_batch,
    score_release_breakdown,
    score_demand,
)
from app.services.taste_service import build_taste_profile
from app.services.search_control import SearchCancelled, check_cancelled
from app.services.inventory_service import (
    link_inventory,
    link_listing,
)


FULL_SCORE_LIMIT = 30
EXPLORATION_SIZE = 5
# Discogs rejects page > 100 for inventories belonging to other users.
INVENTORY_PAGE_LIMIT = 100
DEMAND_RESULT_LIMIT = 30


def _select_candidate_batch(ranked, wantlist_ids, excluded_ids):
    # Keep the entire eligible pool so exploration can reach lower ranks.
    eligible = select_candidates(
        ranked, wantlist_ids, excluded_ids, limit=len(ranked),
    )
    exploit, explore = select_progressive_batch(
        eligible,
        selected_ids=set(),
        exploit_size=FULL_SCORE_LIMIT - EXPLORATION_SIZE,
        explore_size=EXPLORATION_SIZE,
    )
    batch = exploit + explore
    return batch, len(eligible) > len(batch)


def recommend(
    username: str,
    seller: str,
) -> dict:
    # -------------------------
    # USER DATA
    # -------------------------

    collection = get_collection(username)

    collection_ids = {
        release.id
        for release in collection
    }

    taste = prepare_taste(build_taste_profile(
        collection
    ))

    wantlist_ids = set(
        get_wantlist_ids(username)
    )

    # -------------------------
    # INVENTORY SIZE
    # -------------------------

    first_page = get_inventory_raw(
        seller,
        page=1,
        per_page=100,
    )

    reported_pages = first_page[
        "pagination"
    ]["pages"]

    sample_pages = list(range(1, min(reported_pages, INVENTORY_PAGE_LIMIT) + 1))

    # -------------------------
    # INVENTORY
    # -------------------------

    listings = get_inventory(
        seller,
        pages=sample_pages,
    )

    # -------------------------
    # PRE-RANK
    # -------------------------

    ranked = rank_listings(
        listings,
        taste,
        collection_ids,
    )

    candidates, _ = _select_candidate_batch(
        ranked,
        wantlist_ids,
        collection_ids,
    )

    # -------------------------
    # ENRICHMENT
    # -------------------------

    items = link_inventory(
        candidates
    )

    # -------------------------
    # FULL SCORE
    # -------------------------

    ranked_items = rank_inventory_items(
        items,
        taste,
    )

    recommendations = []

    for item, score in ranked_items:

        release = item.release
        listing = item.listing

        breakdown = score_release_breakdown(
            release,
            taste,
        )

        recommendations.append(
            {
                "listing_id": listing.id,
                "release_id": release.id,
                "title": release.title,
                "thumbnail_url": release.thumbnail_url,
                "videos": release.videos,
                "artists": release.artists,
                "labels": release.labels,
                "year": release.year,
                "genres": release.genres,
                "styles": release.styles,
                "price": listing.price,
                "currency": listing.currency,
                "condition": listing.condition,
                "sleeve_condition": (
                    listing.sleeve_condition
                ),
                "score": round(score, 4),
                "score_breakdown": breakdown,
                **_community_counts(listing),
            }
        )

    return {
        "username": username,
        "seller": seller,
        "sample_pages": sample_pages,
        "reported_pages": reported_pages,
        "inventory_truncated": reported_pages > len(sample_pages),
        "sampled_listings": len(listings),
        "candidates": len(candidates),
        "recommendations": recommendations,
    }

def _community_counts(listing) -> dict:
    summary = listing.release_summary
    return {
        "community_want": summary.community_want if summary else None,
        "community_have": summary.community_have if summary else None,
        "demand_score": score_demand(listing),
    }


def _recommendation_payload(item, taste, score=None) -> dict:
    release = item.release
    listing = item.listing
    breakdown = score_release_breakdown(release, taste)
    return {
        "listing_id": listing.id,
        "release_id": release.id,
        "title": release.title,
        "thumbnail_url": release.thumbnail_url,
        "videos": release.videos,
        "artists": release.artists,
        "labels": release.labels,
        "year": release.year,
        "genres": release.genres,
        "styles": release.styles,
        "price": listing.price,
        "currency": listing.currency,
        "condition": listing.condition,
        "sleeve_condition": listing.sleeve_condition,
        "score": round(breakdown["total"] if score is None else score, 4),
        "score_breakdown": breakdown,
        **_community_counts(listing),
    }

def _demand_payload(listing) -> dict:
    """Use inventory metadata without fetching another full release."""
    summary = listing.release_summary
    return {
        "listing_id": listing.id,
        "release_id": listing.release_id,
        "title": summary.title or f"Release {listing.release_id}",
        "thumbnail_url": summary.thumbnail_url,
        "videos": [],
        "artists": [summary.artist] if summary.artist else [],
        "labels": [summary.label] if summary.label else [],
        "year": summary.year,
        "genres": [],
        "styles": [],
        "price": listing.price,
        "currency": listing.currency,
        "condition": listing.condition,
        "sleeve_condition": listing.sleeve_condition,
        "score": 0.0,
        "score_breakdown": {},
        **_community_counts(listing),
    }


def _update_demand_candidates(candidates, listings, excluded_ids):
    for listing in listings:
        check_cancelled()
        if listing.release_id in excluded_ids or score_demand(listing) <= 0:
            continue
        current = candidates.get(listing.release_id)
        if current is None or (listing.price, listing.id) < (current.price, current.id):
            candidates[listing.release_id] = listing
    ranked = sorted(candidates.values(), key=lambda listing: (
        -score_demand(listing), listing.release_id,
    ))
    return [_demand_payload(listing) for listing in ranked[:DEMAND_RESULT_LIMIT]]


def _stream_event(event_type: str, **data) -> str:
    return json.dumps(
        {
            "type": event_type,
            **data,
        },
        ensure_ascii=False,
    ) + "\n"


def recommend_stream(
    username: str,
    seller: str,
    *,
    exclude_release_ids: list[int] | None = None,
    inventory_page_limit: int | None = None,
    include_demand: bool = False,
):
    try:
        # Accept the old page-limit argument for existing clients, but always
        # scan all accessible pages, up to Discogs' limit for other sellers.
        if inventory_page_limit is not None and inventory_page_limit < 1:
            raise ValueError("inventory_page_limit must be positive")
        excluded_ids = set(exclude_release_ids or [])
        # -------------------------
        # USER DATA
        # -------------------------

        yield _stream_event(
            "status",
            message="Loading collection",
        )

        collection = get_collection(username)

        collection_ids = {
            release.id
            for release in collection
        }

        yield _stream_event(
            "status",
            message="Building taste profile",
        )

        taste = prepare_taste(build_taste_profile(
            collection
        ))

        yield _stream_event(
            "status",
            message="Loading wantlist",
        )

        wantlist_ids = set(
            get_wantlist_ids(username)
        )

        # -------------------------
        # INVENTORY SIZE
        # -------------------------

        yield _stream_event(
            "status",
            message="Reading seller inventory",
        )

        first_page = get_inventory_raw(
            seller,
            page=1,
            per_page=100,
        )

        reported_pages = first_page[
            "pagination"
        ]["pages"]

        sample_pages = list(range(1, min(reported_pages, INVENTORY_PAGE_LIMIT) + 1))
        inventory_truncated = reported_pages > len(sample_pages)

        yield _stream_event(
            "start",
            username=username,
            seller=seller,
            sample_pages=sample_pages,
            reported_pages=reported_pages,
            inventory_truncated=inventory_truncated,
        )

        # -------------------------
        # INVENTORY
        # -------------------------

        listings = []
        demand_candidates = {}
        ranker = ListingRanker(taste, collection_ids)

        wantlist_seen = set()
        scored_ids = set()
        attempted_ids = set()
        skipped_ids = set()
        more_candidates = False
        exploit_limit = FULL_SCORE_LIMIT - EXPLORATION_SIZE

        for page in sample_pages:
            check_cancelled()

            # Page 1 is already available
            # from the inventory size request.
            if page == 1:
                page_data = first_page
            else:
                page_data = get_inventory_raw(
                    seller,
                    page=page,
                    per_page=100,
                )

            page_listings = inventory_to_listings(
                page_data
            )

            listings.extend(
                page_listings
            )

            if include_demand:
                yield _stream_event(
                    "demand_results",
                    records=_update_demand_candidates(
                        demand_candidates, page_listings, collection_ids | wantlist_ids,
                    ),
                )

            # Spread the top-candidate budget across the scan, starting on
            # page 1. Reserve exploration for the complete accessible pool.
            ranker.add(page_listings)
            final_page = page == len(sample_pages)
            target = ceil(exploit_limit * page / len(sample_pages))
            eligible = []
            if target > len(attempted_ids) or final_page:
                ranked = ranker.ranked()
                eligible = select_candidates(
                    ranked, wantlist_ids,
                    collection_ids | excluded_ids | attempted_ids | skipped_ids,
                    limit=len(ranked),
                )
            candidates, exploration = select_progressive_batch(
                eligible,
                selected_ids=set(),
                exploit_size=max(0, target - len(attempted_ids)),
                explore_size=EXPLORATION_SIZE if final_page else 0,
            )
            candidates += exploration
            total_candidates = len(attempted_ids) + len(candidates)
            if final_page:
                more_candidates = len(eligible) > len(candidates)
                yield _stream_event(
                    "pre_rank_complete", candidates=total_candidates,
                )

            # Yield each score before fetching another release or enriching
            # wantlist matches, so neither can hold back a ready result.
            for listing in candidates:
                # Missing releases still consume a lookup from the request budget.
                attempted_ids.add(listing.release_id)
                item = link_listing(listing)
                if item is None:
                    skipped_ids.add(listing.release_id)
                    continue
                scored_ids.add(listing.release_id)
                yield _stream_event(
                    "recommendation",
                    processed=len(attempted_ids),
                    candidates=total_candidates if final_page else FULL_SCORE_LIMIT,
                    inventory_scanning=not final_page,
                    recommendation=_recommendation_payload(item, taste),
                )

            # -------------------------
            # WANTLIST MATCHES
            # -------------------------

            for listing in page_listings:
                check_cancelled()

                if (
                    listing.release_id
                    in wantlist_ids
                    and listing.release_id
                    not in collection_ids
                    and listing.release_id not in excluded_ids
                    and listing.release_id not in skipped_ids
                    and listing.release_id
                    not in wantlist_seen
                ):
                    item = link_listing(listing)
                    if item is None:
                        skipped_ids.add(listing.release_id)
                        continue
                    wantlist_seen.add(listing.release_id)

                    yield _stream_event(
                        "wantlist",
                        recommendation=_recommendation_payload(
                            item, taste,
                        ),
                    )

            # -------------------------
            # PROGRESS
            # -------------------------

            yield _stream_event(
                "progress",
                page=page,
                pages=len(sample_pages),
                listings=len(listings),
            )

        yield _stream_event(
            "inventory_complete",
            scanned_pages=len(sample_pages),
            reported_pages=reported_pages,
            inventory_truncated=inventory_truncated,
            listings=len(listings),
            wantlist_matches=len(
                wantlist_seen
            ),
        )

        # -------------------------
        # DONE
        # -------------------------

        yield _stream_event(
            "done",
            recommendations=len(scored_ids),
            has_more=more_candidates,
            next_inventory_page_limit=len(sample_pages),
            inventory_truncated=inventory_truncated,
            wantlist_matches=len(
                wantlist_seen
            ),
        )

    except SearchCancelled:
        raise
    except Exception as exc:

        yield _stream_event(
            "error",
            error_type=type(exc).__name__,
            message=str(exc),
        )
