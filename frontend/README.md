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
