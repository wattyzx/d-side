"""Discogs login, session identity, and logout."""

import secrets
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import ConfigurationError, Settings, get_settings
from app.services.auth_store import AuthStore
from app.services.discogs_oauth import DiscogsOAuth
from app.services.discogs_session import DiscogsCredentials

router = APIRouter(prefix="/auth", tags=["auth"])


@dataclass
class AuthServices:
    oauth: DiscogsOAuth
    store: AuthStore
    settings: Settings


@lru_cache(maxsize=1)
def get_auth_services() -> AuthServices:
    try:
        settings = get_settings()
        settings.require_auth_configuration()
    except ConfigurationError as exc:
        raise HTTPException(503, str(exc)) from None
    store = AuthStore(settings.auth_db_path, settings.auth_encryption_key)
    oauth = DiscogsOAuth(settings.discogs_consumer_key, settings.discogs_consumer_secret)
    return AuthServices(oauth, store, settings)


def cookie(response, name, value, ttl, services):
    response.set_cookie(name, value, max_age=ttl, httponly=services.settings.cookie_httponly,
                        secure=services.settings.cookie_secure,
                        samesite=services.settings.cookie_samesite, path=services.settings.cookie_path)


def private_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def login_failure(services, code):
    response = RedirectResponse(services.settings.frontend_url + "?" + urlencode({"auth_error": code}), status_code=302)
    response.delete_cookie(services.settings.pending_cookie_name, path="/auth")
    response.delete_cookie(services.settings.pending_cookie_name, path=services.settings.cookie_path)
    return private_response(response)


@router.get("/discogs/login")
def login(request: Request, services: AuthServices = Depends(get_auth_services)):
    try:
        tokens = services.oauth.begin(services.settings.callback_url)
    except (httpx.HTTPError, ValueError):
        return login_failure(services, "provider")
    old_pending = request.cookies.get(services.settings.pending_cookie_name)
    if old_pending:
        services.store.delete("pending", old_pending)
    pending = services.store.create("pending", {
        "token": tokens["oauth_token"], "secret": tokens["oauth_token_secret"],
    }, services.settings.pending_ttl_seconds)
    response = RedirectResponse(services.oauth.authorize_url(tokens["oauth_token"]), status_code=302)
    cookie(response, services.settings.pending_cookie_name, pending, services.settings.pending_ttl_seconds, services)
    return private_response(response)


@router.get("/discogs/callback")
def callback(request: Request, services: AuthServices = Depends(get_auth_services)):
    identifier = request.cookies.get(services.settings.pending_cookie_name)
    token = request.query_params.get("oauth_token", "")
    verifier = request.query_params.get("oauth_verifier", "")
    if not identifier or not token or not verifier:
        return login_failure(services, "incomplete")
    pending = services.store.read("pending", identifier)
    if not pending or not secrets.compare_digest(pending["token"].encode(), token.encode()):
        return login_failure(services, "expired")
    pending = services.store.read("pending", identifier, consume=True)
    if not pending:
        return login_failure(services, "used")
    try:
        credentials = services.oauth.finish(token, pending["secret"], verifier)
    except (httpx.HTTPError, ValueError):
        return login_failure(services, "provider")
    old_session = request.cookies.get(services.settings.session_cookie_name)
    if old_session:
        services.store.delete("session", old_session)
    session = services.store.create("session", credentials, services.settings.session_ttl_seconds)
    response = RedirectResponse(services.settings.frontend_url, status_code=302)
    response.delete_cookie(services.settings.pending_cookie_name, path="/auth")
    response.delete_cookie(services.settings.pending_cookie_name, path=services.settings.cookie_path)
    cookie(response, services.settings.session_cookie_name, session, services.settings.session_ttl_seconds, services)
    return private_response(response)


def require_account(request: Request, services: AuthServices = Depends(get_auth_services)) -> DiscogsCredentials:
    session = request.cookies.get(services.settings.session_cookie_name)
    credentials = services.store.read("session", session) if session else None
    if not credentials:
        raise HTTPException(401, "Sign in with Discogs.")
    return DiscogsCredentials(**credentials, consumer_key=services.oauth.consumer_key,
                              consumer_secret=services.oauth.consumer_secret)


def trusted_origin(request: Request, services: AuthServices = Depends(get_auth_services)):
    if request.headers.get("origin") not in services.settings.trusted_origins:
        raise HTTPException(403, "Untrusted request origin.")


@router.get("/me")
def me(account: DiscogsCredentials = Depends(require_account)):
    return private_response(JSONResponse({"authenticated": True, "username": account.username}))


@router.post("/logout")
def logout(request: Request, services: AuthServices = Depends(get_auth_services),
           _=Depends(trusted_origin)):
    # A required trusted Origin prevents cross-site session mutations.
    for kind, name in (("session", services.settings.session_cookie_name), ("pending", services.settings.pending_cookie_name)):
        identifier = request.cookies.get(name)
        if identifier:
            services.store.delete(kind, identifier)
    response = JSONResponse({"authenticated": False})
    for name in (services.settings.session_cookie_name, services.settings.pending_cookie_name):
        response.delete_cookie(name, path="/auth")
        response.delete_cookie(name, path=services.settings.cookie_path)
    return private_response(response)
