# D(e)Side frontend

The standalone frontend uses HTML, CSS, and DOM JavaScript. Its API and session
modules are TypeScript, transpiled by Vite. No React or TanStack dependency is
needed. Login, streamed results, cancellation, Search more, and wantlist saves
use the same FastAPI backend.

From the project root:

```sh
npm ci --prefix frontend
./run.sh
```

Open **http://localhost:5173**. Vite proxies `/auth`, `/recommend`, and `/wantlist`
to FastAPI. OAuth returns directly to this frontend. Use `localhost` consistently;
there is no development Origin rewrite. The default backend settings already
trust this address.

For production serving:

```sh
npm run build --prefix frontend
FRONTEND_URL=http://localhost:8000 ./run-production.sh
```

FastAPI serves `frontend/dist` and the API from the same origin. Set the
public HTTPS `FRONTEND_URL` when hosting and update any explicit OAuth callback
URL to match. Rebuild after frontend changes.

## Results and previews

The seller field accepts usernames, Discogs seller shop/profile URLs, user
profile URLs, and marketplace URLs containing a `seller` query parameter.
Release and individual listing URLs do not identify a seller and are rejected.

Search results and price filters are saved in the current tab's session storage
for up to 24 hours. Refresh restores them after confirming the account. An
interrupted search is automatically resumed with a new request after cancelling
and waiting for its previous worker; previously received recommendations and
wantlist matches are excluded from the new batch. This can rescan cached pages
and select additional candidates; it does not keep the original worker running
while the page is closed. Completed searches restore without starting another
request. Signing out or an expired session clears saved results. If browser
storage is disabled or full, the UI warns that refresh recovery is unavailable.

**Buy on Discogs** opens the exact marketplace listing in a new tab. Add the item
to the cart there using the Discogs website; the app does not claim to have
modified the Discogs cart.

Results use three tabs: Recommendations, Wantlist, and On demand. On demand
ranks up to 30 distinct releases from the scanned inventory using the backend's
community demand score, excluding owned and wantlisted records. It needs no
additional full-release requests. Covers and styles may be unavailable there.

Recommendations and wantlist matches can include YouTube videos. Click a
playable cover to open the preview player; previews require an available,
embeddable video. Inventory-only demand records have no videos.

## Checks

```sh
npm test --prefix frontend
npm run build --prefix frontend
npm run lint --prefix frontend
```

Tests cover authentication, session changes, streaming, cancellation, saves,
and player behavior. The build type-checks the TypeScript modules before Vite
bundles the frontend. Manually verify login, progressive results, cancellation,
Search more, saves, logout, previews, and the layout on a narrow screen.
