from app.services.discogs_client import (
    get_collection,
    get_inventory,
    get_inventory_raw,
    get_wantlist_ids,
)
from app.services.inventory_service import link_inventory
from app.services.recommender import (
    rank_inventory_items,
    rank_listings,
    select_candidates,
    score_release_breakdown,
)
from app.services.taste_service import build_taste_profile


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