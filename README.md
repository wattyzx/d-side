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
- **Persistent login:** OAuth credentials stay encrypted in SQLite; the browser receives an HttpOnly session cookie. Pending logins expire after ten minutes, sessions after seven days, and signing out deletes the local session and credentials.

## Run locally

**Python 3.10+**, **Node.js 22.12+**, and a registered Discogs application.
From the project folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm install --prefix frontend
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

### Serve the built frontend with FastAPI

Frontend serving is optional and disabled by default. After building React, enable it to serve the website and API from the same address without Vite:

```sh
npm run build --prefix frontend
FRONTEND_URL=http://localhost:8000 ./run-production.sh
```

Open `http://localhost:8000`. The default Discogs callback becomes
`http://localhost:8000/auth/discogs/callback`; if you explicitly set
`DISCOGS_CALLBACK_URL`, update it to match. For hosting, set `FRONTEND_URL` to
the public HTTPS origin. Authentication and API routes keep their existing paths.
Enabling serving without `frontend/dist/index.html` fails at startup with a build
instruction. Rebuild React after frontend changes.

`run-production.sh` enables frontend serving and starts one Uvicorn worker
without development reload. It checks for the Python environment and frontend
build, and binds to `0.0.0.0:8000` by default. Override `HOST` or `PORT` through
environment variables when needed. Set `FRONTEND_URL` and any explicit
`DISCOGS_CALLBACK_URL` in the environment or `.env`; the script does not replace
these URL settings. Press **Ctrl+C** to stop the server.

## Stack

- **Frontend:** React, TypeScript, Vite, and TanStack Query.
- **Backend:** Python, FastAPI, Pydantic, and Uvicorn; HTTPX for Discogs requests.
- **Authentication:** Discogs OAuth via OAuthlib, encrypted credentials via Cryptography.
- **Storage:** SQLite for sessions and response caches, plus a bounded in-memory release cache.
- **Recommendations:** Deterministic metadata scoring; no trained model yet.

To run the checks:

```sh
.venv/bin/python -m unittest discover -s tests -v
npm test --prefix frontend
npm run build --prefix frontend
npm run lint --prefix frontend
```

Tests use mocked Discogs responses and need no live credentials.

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
Authentication and response caches currently use local SQLite storage.

## TODO

Candidate selection:

- [ ] Build a dataset of releases with artists, labels, years, and styles; hold evaluation releases apart from training data.
- [ ] Train a simple baseline to predict likely styles from listing metadata.
- [ ] Compare candidate relevance with the current pre-ranker under the same full-metadata request budget.
- [ ] Integrate behind a feature flag, retaining the current fallback and actual Discogs styles for final scoring.
- [ ] Evaluate artist and label similarity after the baseline.

Implementations:

- [ ] Link or embedd a player for the records available on digital platforms. Discogs may have YouTube link attached to some releases.
- [ ] Add a **Add to cart** button next to each release. 

Steps towards deployment:

- [ ] Move response caches and authentication storage to persistent Turso storage.
- [ ] Configure production routing for authentication, recommendations, and wantlist saves. Verify streaming.
- [ ] Set production secrets, a stable encryption key, HTTPS URLs, and allowed origins. Verify OAuth and secure cookies.
- [ ] Deploy one backend instance with one worker and a `/health` check.
- [ ] Pass Python tests, frontend tests, production build, and lint checks.
- [ ] Test load limitations. Need to establish `MAX_CONCURRENT_USERS`.
- [ ] Smoke-test login, refresh, search, cancellation, **Search more**, saves, and logout; verify persistence across restarts and behavior after hosting sleep.

## What’s next

**Hosted prototype:** The proposed setup is a React static site and FastAPI service on Render, with Turso for persistent storage. Deployment is still planned.

**Artist and label similarity:** Explore shared styles, release eras, and catalogue relationships to surface unfamiliar but related names. Start with a simple similarity baseline, then evaluate graph embeddings as a small pre-ranking bonus.
This is proposed and has not been trained or integrated; see the
[artist and label similarity experiment](docs/artist-label-similarity.md).

**Style pre-ranking:** Test whether predicted styles select better candidates within the same request budget. 
