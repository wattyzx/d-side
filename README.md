# D(e)Side

**Decide what to dig.**

D(e)Side helps you find records you might like in a Discogs seller’s inventory.
It uses your collection and wantlist to suggest what to check out next.
Wantlist matches appear as the inventory is scanned, and recommendations appear as they are scored.
You can open each record on Discogs or add it straight to your wantlist.

## How it works

1. **Log in with Discogs.** OAuth connects your account and creates a persistent session.
2. **Load your collection and wantlist.** Your collection defines your taste profile: styles, genres, artists, labels, and release years. Your wantlist identifies records you already want.
3. **Pick a seller.** The app scans their inventory page by page, skipping releases you own and showing wantlist matches as it finds them.
4. **Pre-rank candidates.** With the fetched metadata (artist, label, year, and demand) from the seller's inventory, the pre-rank select up to 25 promising releases progressively. After the scan, up to 5 additional releases from across the remaining pool give less obvious matches a chance.
5. **Calculate the final score.** Selected releases get their full Discogs metadata. Musical styles drive the score, with smaller artist, label, and year bonuses; genres provide a fallback when style comparison is unavailable. Recommendations above **0.1** are shown; wantlist matches do not need to meet this threshold.

Results arrive during the search. **Search more** scores another batch of unseen releases from the scanned inventory. **Cancel search** keeps results already received and stops further work once any in-flight Discogs request finishes or times out.

## Design choices and issues solved

- **Two stage ranking:** Marketplace summaries lack musical styles. Pre-ranking uses available metadata to limit full requests to a small candidate batch, balancing discovery with Discogs rate limits. Early candidates depend on the inventory scanned so far, so they can differ from a ranking of the complete inventory.
- **Page limit:** Discogs blocks inventory pages above 100 for other sellers. At 100 listings per page, searches cover at most **10,000 listings**. Larger inventories show an incomplete-results notice; **Search more** stays within those accessible pages.
- **Responsive searches:** Results stream progressively. A separate search worker pool keeps login, health checks, and cancellation responsive. One search is allowed per account across browser tabs. Search IDs prevent delayed cancellation from stopping a newer search.
- **Less repeated work:** Taste lookups and listing scores are reused during scans. Discogs responses and release metadata are cached, and expired storage is cleaned regularly.
- **Shared rate limits:** Requests are paced across accounts, and retries respect upstream cooldowns. Rate-limit feedback is retained even when a request’s search is cancelled.
- **Account isolation:** Personal caches are separated by account; public release metadata can be shared. Wantlist saves invalidate cached data atomically, preventing older in-flight fetches from restoring stale responses.
- **Persistent login:** OAuth credentials stay encrypted in the configured database; the browser receives an HttpOnly session cookie. Pending logins expire after ten minutes, sessions after seven days, and signing out deletes the stored session and credentials.

## Run locally

**Python 3.10+**, **Node.js 22.12+**, and a registered Discogs application.
From the project folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm ci --prefix frontend
```
Discogs application token:

```env
DISCOGS_CONSUMER_KEY=your_key_here
DISCOGS_CONSUMER_SECRET=your_secret_here
AUTH_ENCRYPTION_KEY=your_generated_key_here
```

Start both servers:

```sh
./run.sh
```

Vite proxies API and authentication requests to the backend. Use `localhost:5173` consistently.

Press **Ctrl+C** to stop both servers. Later starts use `.venv` automatically.
Restart the servers after changing configuration.

The standalone frontend lives in `frontend/`. See [the frontend guide](frontend/README.md) for its code, tests, and player behavior.

### Serve the built frontend with FastAPI

Frontend serving is optional and disabled by default. After building the frontend, enable it to serve the website and API from the same address without Vite:

```sh
npm run build --prefix frontend
FRONTEND_URL=http://localhost:8000 ./run-production.sh
```

Open `http://localhost:8000`. The default Discogs callback becomes
`http://localhost:8000/auth/discogs/callback`; if you explicitly set
`DISCOGS_CALLBACK_URL`, update it to match. For hosting, set `FRONTEND_URL` to
the public HTTPS origin. Authentication and API routes keep their existing paths.
Enabling serving without `frontend/dist/index.html` fails at startup with a build instruction.

`run-production.sh` enables frontend serving and starts one Uvicorn worker
without development reload. It checks for the Python environment and frontend
build, and binds to `0.0.0.0:8000` by default. Override `HOST` or `PORT` through
environment variables when needed. Set `FRONTEND_URL` and any explicit
`DISCOGS_CALLBACK_URL` in the environment or `.env`; the script does not replace
these URL settings. Press **Ctrl+C** to stop the server.

### Production routing and streaming

Route the entire public HTTPS origin to the single Uvicorn service started by
`run-production.sh`. FastAPI serves `/` and build assets, while `/auth/*`,
`/recommend`, `/recommend/stream`, `/recommend/cancel`, `/wantlist`, and `/health`
retain their backend routes. The frontend uses relative API URLs; no separate
API hostname or Vite development proxy is needed in production.

On the deployed domain, verify:

1. `/` loads the built frontend and its assets; `/health` returns JSON.
2. Discogs login returns to the same domain and `/auth/me` identifies the user.
3. Start a search with an uncached collection or seller. In browser developer
   tools, inspect `/recommend/stream`: it must return NDJSON, and the UI must
   update while the request is still pending, not only when it completes.
4. Cancel an active search, then run **Search more**. Confirm a new search can
   start after cancellation and results continue arriving progressively.
5. Save a record to the wantlist and confirm it on Discogs, then log out.

Repeat the streaming check through the public domain, not just localhost. Keep
the deployment checklist item open until that proxy-level check passes.

### Storage: SQLite or Turso

SQLite remains the default. To use the Turso **libSQL** database, add its
credentials to `.env`:

```env
TURSO_DATABASE_URL=libsql://your-database.turso.io
TURSO_AUTH_TOKEN=your_database_token
```

Keep the existing `AUTH_ENCRYPTION_KEY` stable across restarts and deployments.
The backend uses Turso's [SQL-over-HTTP API](https://docs.turso.tech/sdk/http/reference)
through the existing HTTPX dependency. No additional package is required.

First check the connection and storage behavior:

```sh
STORAGE_BACKEND=turso .venv/bin/python -m app.check_storage
```

After the check passes, add `STORAGE_BACKEND=turso` to `.env` and restart the
app. Sessions and caches then use Turso. Local SQLite files are retained but
are not uploaded; log in again and let the caches rebuild. Set
`STORAGE_BACKEND=sqlite` to return to local storage. The database token is used
only by the backend.

`DATABASE_TIMEOUT_SECONDS` defaults to 10 for HTTP operations and local SQLite
lock waits. Failed remote operations return a safe error and are not silently
retried or redirected to local storage. Transactions hold the remote connection
only for database work, never while fetching Discogs data.

## Stack

- **Frontend:** HTML, CSS, vanilla JavaScript, TypeScript API/session modules, and Vite.
- **Backend:** Python, FastAPI, Pydantic, and Uvicorn; HTTPX for Discogs requests.
- **Authentication:** Discogs OAuth via OAuthlib, encrypted credentials via Cryptography.
- **Storage:** SQLite locally or Turso for sessions and response caches, plus a bounded in-memory release cache.
- **Recommendations:** Deterministic metadata scoring; no trained model yet.

To run the checks:

```sh
STORAGE_BACKEND=sqlite .venv/bin/python -m unittest discover -s tests -v
npm test --prefix frontend
npm run build --prefix frontend
npm run lint --prefix frontend
```

Tests use mocked Discogs and Turso responses and need no live credentials.
The explicit SQLite setting keeps unit tests local even when `.env` enables
Turso. The separate `app.check_storage` command checks the real database.

## Known limitations

**Candidate generation:** Pre-ranking relies on artist, label, year, and demand.
It can miss unfamiliar releases that would score well on musical styles once
their full metadata is loaded. Exploration helps, but only selected candidates
receive a final score.

**Inventory coverage:** Sellers with more than 10,000 listings cannot be fully
scanned through the accessible pages. First searches of large inventories take
longer before caches are populated.

**Deployment:** Search coordination and rate limiting are process-local. Use
**one backend instance with one Uvicorn worker** until this state is shared.
Authentication and response caches support local SQLite or remote Turso storage.

## TODO

Candidate selection:

- [ ] Build a dataset of releases with artists, labels, years, and styles; keep evaluation releases and their alternate editions apart from training data.
- [ ] Build an artist/label style-frequency baseline, then train one-vs-rest logistic regression to predict styles from listing metadata.
- [ ] Compare both approaches with the current pre-ranker under the same progressive selection behavior and full-metadata request budget; see the [style pre-ranking proposal](docs/style-pre-ranking.md).
- [ ] Integrate behind a feature flag, retaining the current fallback and actual Discogs styles for final scoring.
- [ ] Evaluate artist and label similarity after the baseline.

Implementations:

- [X] Keep searches running when an individual release lookup returns 404 or 410: skip the release in both recommendation and wantlist enrichment, and track skipped IDs to avoid retrying another copy during the same search. Continue surfacing authentication failures, rate limits, and exhausted network retries as search errors.
- [X] Add regression tests for a permanently unavailable candidate and wantlist release: later valid records must still be emitted and the stream must reach `done`.
- [X] Link or embedd a player for the records available on digital platforms. Discogs may have YouTube link attached to some releases.
- [ ] Add a **Add to cart** button next to each release. 

Steps towards deployment:

- [X] Enable Turso storage and pass the live storage check for sessions and response caches.
- [ ] Configure production routing for authentication, recommendations, and wantlist saves. Verify streaming.
- [ ] Set production secrets, a stable encryption key, HTTPS URLs, and allowed origins. Verify OAuth and secure cookies.
- [ ] Deploy one backend instance with one worker and a `/health` check.
- [ ] Pass Python tests, frontend tests, production build, and lint checks.
- [ ] Test load limitations. Need to establish `MAX_CONCURRENT_USERS`.
- [ ] Smoke-test login, refresh, search, cancellation, **Search more**, saves, and logout; verify persistence across restarts and behavior after hosting sleep.

## What’s next

**Hosted prototype:** The proposed setup is one FastAPI service serving the built vanilla frontend, with Turso for persistent storage. Deployment is still planned.

**Style pre-ranking:** Start with artist/label style frequencies, then test one-vs-rest logistic regression using artist, label, and year. Compare predicted styles with the user's collection profile to help select promising records before fetching full metadata. Evaluate offline under the existing 30-release enrichment budget, retaining five exploration slots and actual Discogs styles for final scoring. This is proposed; no model has been trained or integrated. See the [style pre-ranking proposal](docs/style-pre-ranking.md).

**Artist and label similarity:** After the style baseline, explore shared styles, release eras, and catalogue relationships to surface unfamiliar but related names. Start with a simple similarity baseline, then evaluate graph embeddings such as node2vec as a small pre-ranking bonus.
This is proposed and has not been trained or integrated; see the
[artist and label similarity experiment](docs/artist-label-similarity.md).
