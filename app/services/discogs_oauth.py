"""Discogs OAuth 1.0a handshake; credentials never leave the backend."""

from urllib.parse import parse_qsl, urlencode

import httpx
from oauthlib.oauth1 import Client

from app.services.discogs_http import BASE_URL


class DiscogsOAuth:
    def __init__(self, consumer_key: str, consumer_secret: str):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret

    def request(self, method: str, path: str, *, token=None, secret=None,
                callback=None, verifier=None) -> httpx.Response:
        signer = Client(
            self.consumer_key, client_secret=self.consumer_secret,
            resource_owner_key=token, resource_owner_secret=secret,
            callback_uri=callback, verifier=verifier,
        )
        url, headers, body = signer.sign(
            BASE_URL + path, http_method=method,
            headers={"User-Agent": "D(e)Side/0.1"},
        )
        response = httpx.request(method, url, headers=headers, content=body, timeout=10)
        response.raise_for_status()
        return response

    @staticmethod
    def tokens(response: httpx.Response) -> dict:
        values = dict(parse_qsl(response.text))
        if not values.get("oauth_token") or not values.get("oauth_token_secret"):
            raise ValueError("Invalid OAuth token response")
        return values

    def begin(self, callback: str) -> dict:
        tokens = self.tokens(self.request("POST", "/oauth/request_token", callback=callback))
        if tokens.get("oauth_callback_confirmed") != "true":
            raise ValueError("Discogs did not confirm the callback")
        return tokens

    def finish(self, token: str, secret: str, verifier: str) -> dict:
        tokens = self.tokens(self.request(
            "POST", "/oauth/access_token", token=token, secret=secret, verifier=verifier,
        ))
        identity = self.request(
            "GET", "/oauth/identity", token=tokens["oauth_token"],
            secret=tokens["oauth_token_secret"],
        ).json()
        if not isinstance(identity.get("username"), str) or not identity["username"]:
            raise ValueError("Discogs did not return a username")
        return {"username": identity["username"], "token": tokens["oauth_token"],
                "secret": tokens["oauth_token_secret"]}

    @staticmethod
    def authorize_url(token: str) -> str:
        return "https://www.discogs.com/oauth/authorize?" + urlencode({"oauth_token": token})
