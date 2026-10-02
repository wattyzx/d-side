import json

from app.services.discogs_client import (
    get_collection,
    get_inventory,
    get_inventory_raw,
    get_wantlist_ids,
)
from app.services.release_mapper import inventory_to_listings
from app.services.recommender import (
    rank_inventory_items,
    rank_listings,
    select_candidates,
    score_release_breakdown,
)
from app.services.taste_service import build_taste_profile
from app.services.inventory_service import (
    link_inventory,
    link_listing,
)


SAMPLE_PAGE_LIMIT = 10
FULL_SCORE_LIMIT = 30


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

    taste = build_taste_profile(
        collection
    )

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

    sample_pages = list(
        range(
            1,
            min(
                reported_pages,
                SAMPLE_PAGE_LIMIT,
            ) + 1,
        )
    )

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

    candidates = select_candidates(
        ranked,
        wantlist_ids,
        collection_ids,
        limit=FULL_SCORE_LIMIT,
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
            }
        )

    return {
        "username": username,
        "seller": seller,
        "sample_pages": sample_pages,
        "sampled_listings": len(listings),
        "candidates": len(candidates),
        "recommendations": recommendations,
    }

def _recommendation_payload(item, taste, score=None) -> dict:
    release = item.release
    listing = item.listing
    breakdown = score_release_breakdown(release, taste)
    return {
        "listing_id": listing.id,
        "release_id": release.id,
        "title": release.title,
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
    }

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
):
    try:
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

        taste = build_taste_profile(
            collection
        )

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

        sample_pages = list(
            range(
                1,
                min(
                    reported_pages,
                    SAMPLE_PAGE_LIMIT,
                ) + 1,
            )
        )

        yield _stream_event(
            "start",
            username=username,
            seller=seller,
            sample_pages=sample_pages,
            reported_pages=reported_pages,
        )

        # -------------------------
        # INVENTORY
        # -------------------------

        listings = []

        wantlist_seen = set()

        for page in sample_pages:

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

            # -------------------------
            # WANTLIST MATCHES
            # -------------------------

            for listing in page_listings:

                if (
                    listing.release_id
                    in wantlist_ids
                    and listing.release_id
                    not in collection_ids
                    and listing.release_id
                    not in wantlist_seen
                ):
                    wantlist_seen.add(
                        listing.release_id
                    )

                    yield _stream_event(
                        "wantlist",
                        recommendation=_recommendation_payload(
                            link_listing(listing), taste,
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
            listings=len(listings),
            wantlist_matches=len(
                wantlist_seen
            ),
        )

        # -------------------------
        # PRE-RANK
        # -------------------------

        yield _stream_event(
            "status",
            message="Ranking candidates",
        )

        ranked = rank_listings(
            listings,
            taste,
            collection_ids,
        )

        candidates = select_candidates(
            ranked,
            wantlist_ids,
            collection_ids,
            limit=FULL_SCORE_LIMIT,
        )

        yield _stream_event(
            "pre_rank_complete",
            candidates=len(candidates),
        )

        # -------------------------
        # ENRICHMENT
        # -------------------------

        yield _stream_event(
            "status",
            message="Loading release details",
        )

        # Enrich and score one candidate at a time so the first result does
        # not have to wait for every Discogs release request to finish.
        for index, listing in enumerate(candidates, start=1):
            item = link_listing(listing)
            yield _stream_event(
                "recommendation",
                processed=index,
                candidates=len(candidates),
                recommendation=_recommendation_payload(item, taste),
            )

        # -------------------------
        # DONE
        # -------------------------

        yield _stream_event(
            "done",
            recommendations=len(candidates),
            wantlist_matches=len(
                wantlist_seen
            ),
        )

    except Exception as exc:

        yield _stream_event(
            "error",
            error_type=type(exc).__name__,
            message=str(exc),
        )
