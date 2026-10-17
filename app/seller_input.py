"""Accept a username or a Discogs seller/profile URL without fetching URLs."""

import re
from urllib.parse import parse_qs, unquote, urlsplit


def normalize_seller(value: str) -> str:
    value = value.strip()
    message = "Enter a seller username or a Discogs shop/profile URL."
    if re.fullmatch(r"[\w.-]+", value) and len(value) <= 100:
        # Bare hostnames are not seller names when pasted without a scheme.
        if value.lower() not in {"discogs.com", "www.discogs.com", ".", ".."}:
            return value
    if value.lower().startswith(("discogs.com/", "www.discogs.com/")):
        value = "https://" + value
    try:
        url = urlsplit(value)
        if (url.scheme not in {"http", "https"}
                or url.hostname not in {"discogs.com", "www.discogs.com"}
                or url.username or url.password or url.port not in {None, 80, 443}
                or "\\" in value):
            raise ValueError(message)
        parts = url.path.strip("/").split("/")
        if parts and re.fullmatch(r"[a-z]{2}(?:-[A-Z]{2})?", parts[0]):
            parts = parts[1:]
        if len(parts) == 2 and parts[0] == "user":
            seller = unquote(parts[1])
        elif (len(parts) in {2, 3} and parts[0] == "seller"
              and (len(parts) == 2 or parts[2] in {"profile", "shop"})):
            seller = unquote(parts[1])
        elif parts == ["sell", "list"]:
            sellers = parse_qs(url.query).get("seller", [])
            if len(sellers) != 1:
                raise ValueError(message)
            seller = sellers[0]
        else:
            raise ValueError(message)
        if not re.fullmatch(r"[\w.-]+", seller) or len(seller) > 100 or seller in {".", ".."}:
            raise ValueError(message)
        return seller
    except ValueError:
        raise ValueError(message) from None
