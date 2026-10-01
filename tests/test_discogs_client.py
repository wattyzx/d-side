from unittest.mock import patch

from app.services.discogs_client import get_inventory


def test_get_inventory_fetches_only_selected_pages():
    pages = [1, 3, 7]

    def fake_inventory_raw(username, page=1, per_page=100):
        return {
            "page": page,
            "pagination": {
                "pages": 10,
            },
        }

    def fake_inventory_to_listings(data):
        return [data["page"]]

    with (
        patch(
            "app.services.discogs_client.get_inventory_raw",
            side_effect=fake_inventory_raw,
        ) as mock_get,
        patch(
            "app.services.discogs_client.inventory_to_listings",
            side_effect=fake_inventory_to_listings,
        ),
    ):
        result = get_inventory("seller", pages=pages)

    assert result == [1, 3, 7]

    assert [
        call.kwargs["page"]
        for call in mock_get.call_args_list
    ] == [1, 3, 7]