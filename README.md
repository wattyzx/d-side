# D-side

**Decide what to dig.**

[Try D-side](https://d-side-6sxd.onrender.com/)

D-side helps you discover records in a Discogs seller’s inventory, using your collection and wantlist to guide the search. Find records that match your taste, spot releases you already want, and explore what to dig next.

Results appear as the search progresses. Preview releases with available YouTube videos, save discoveries to your wantlist, or open the exact listing on Discogs.

## Using D-side

1. **Connect your Discogs account** and load your collection and wantlist.
2. **Choose a seller** by entering their username or pasting a Discogs shop or profile URL.
3. **Explore the results:** personalized recommendations, wantlist matches, and the **On demand** tab for releases ranked by community demand. Records you already own are excluded.
4. **Keep digging.** Use **Search more** to score another batch, or **Buy on Discogs** to open a listing and purchase it there.

## How recommendations work

1. **Build a taste profile.** Your collection provides signals from styles, genres, artists, labels, and release years. Your wantlist identifies exact matches separately.
2. **Select candidates.** As the inventory is scanned, artist, label, year, and demand help select up to 25 promising releases. After the scan, up to five additional releases from the remaining pool give less obvious matches a chance.
3. **Score recommendations.** Selected releases receive full Discogs metadata. Musical styles drive the score, with smaller artist, label, and year bonuses; genres provide a fallback when style comparison is unavailable. Recommendations with scores above **0.1** are shown; wantlist matches bypass this threshold.

Results arrive during the search. **Search more** scores another batch of unseen releases from the scanned inventory. **Cancel search** keeps results already received and stops further work once any in-flight Discogs request finishes or times out.

Refreshing restores results and filters in the same browser tab and automatically
resumes an interrupted search after its previous worker stops. This starts a new
batch excluding received results, rather than keeping the original search alive
in the background. Saved results expire after 24 hours and are cleared on logout.
**Buy on Discogs** opens the exact listing, where you can add it to your cart.

## Design choices

- **Two-stage ranking:** Marketplace summaries lack musical styles. Pre-ranking uses available metadata to limit full requests to a small candidate batch, balancing discovery with Discogs rate limits. Early candidates depend on the inventory scanned so far, so they can differ from a ranking of the complete inventory.
- **Page limit:** Discogs blocks inventory pages above 100 for other sellers. At 100 listings per page, searches cover at most **10,000 listings**. Larger inventories show an incomplete-results notice; **Search more** stays within those accessible pages.
- **Responsive searches:** Results stream progressively. A separate search worker pool keeps login, health checks, and cancellation responsive. One search is allowed per account across browser tabs. Search IDs prevent delayed cancellation from stopping a newer search.
- **Less repeated work:** Taste lookups and listing scores are reused during scans. Discogs responses and release metadata are cached, and expired storage is cleaned regularly.
- **Shared rate limits:** Requests are paced across accounts, and retries respect upstream cooldowns. Rate-limit feedback is retained even when a request’s search is cancelled.
- **Account isolation:** Personal caches are separated by account; public release metadata can be shared. Wantlist saves invalidate cached data atomically, preventing older in-flight fetches from restoring stale responses.
- **Persistent login:** OAuth credentials stay encrypted in the configured database; the browser receives an HttpOnly session cookie. Pending logins expire after ten minutes, sessions after seven days, and signing out deletes the stored session and credentials.

## Run locally

You’ll need **Python 3.10+**, **Node.js** (the project version is pinned in `.nvmrc`), and a registered Discogs application. The commands below use `nvm` to select Node.js.

### 1. Install dependencies

From the project root:

```sh
nvm install
nvm use
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm ci --prefix frontend
```

### 2. Configure authentication

Create a `.env` file in the project root with your Discogs application credentials and a Fernet encryption key:

```env
DISCOGS_CONSUMER_KEY=your_key_here
DISCOGS_CONSUMER_SECRET=your_secret_here
AUTH_ENCRYPTION_KEY=your_generated_key_here
```

Generate the encryption key with:

```sh
.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Copy the output into `AUTH_ENCRYPTION_KEY` and keep this key stable between restarts. For local development, use `http://localhost:5173/auth/discogs/callback` as the Discogs callback URL. SQLite is the default storage backend.

### 3. Start the app

```sh
./run.sh
```

Open **http://localhost:5173**. Vite proxies API and authentication requests to the backend. Use `localhost` consistently for the login flow.

Press **Ctrl+C** to stop both servers. Later starts use `.venv` automatically.
Restart the servers after changing configuration.

The standalone frontend lives in `frontend/`. See [the frontend guide](frontend/README.md) for its code, tests, and player behavior.

## Deployment

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

For a host with Python 3.10+ and Node.js 22.12+ available, use the repository
root as the working directory and these commands:

| Setting | Value |
| --- | --- |
| Build command | `bash build-production.sh` |
| Start command | `bash run-production.sh` |
| Instances | `1` |
| Uvicorn workers | `1` (set by the start script) |
| Health check path | `/health` |

The build script installs backend dependencies into `.venv`, installs frontend
dependencies from the lockfile (including build tools), and builds
`frontend/dist`. Both directories must be available in the runtime environment.
The start script binds to `0.0.0.0` and uses the host's `PORT` environment variable
or port `8000` by default. `/health` checks process liveness only.
Configure secrets and production URLs through the host's environment settings.
For Render, use the repository configuration described below.

Route the entire public HTTPS origin to the single Uvicorn service started by
`run-production.sh`. FastAPI serves `/` and build assets, while `/auth/*`,
`/recommend`, `/recommend/stream`, `/recommend/cancel`, `/wantlist`, and `/health`
retain their backend routes. The frontend uses relative API URLs; no separate
API hostname or Vite development proxy is needed in production.

### Render

[render.yaml](render.yaml) defines a single Render web service with Turso storage, secure cookies, and a `/health` check. It uses `build-production.sh` to build and `run-render.sh` to start the app.

Set these secrets in Render’s environment settings:

- `DISCOGS_CONSUMER_KEY` and `DISCOGS_CONSUMER_SECRET`
- `AUTH_ENCRYPTION_KEY` — keep the same key across deployments
- `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`

The Render start script uses `RENDER_EXTERNAL_URL` as the public origin unless `FRONTEND_URL` is explicitly set. For a custom domain, set `FRONTEND_URL` to that HTTPS origin and update any explicit `DISCOGS_CALLBACK_URL` to match.

### Deployment checks

On the deployed domain, verify:

1. `/` loads the built frontend and its assets; `/health` returns JSON.
2. Discogs login returns to the same domain and `/auth/me` identifies the user.
3. Start a search with an uncached collection or seller. In browser developer
   tools, inspect `/recommend/stream`: it must return NDJSON, and the UI must
   update while the request is still pending, not only when it completes.
4. Cancel an active search, then run **Search more**. Confirm a new search can
   start after cancellation and results continue arriving progressively.
5. Save a record to the wantlist and confirm it on Discogs, then log out.

Run the streaming check through the public domain to verify that the hosting proxy delivers results progressively.

## Stack

- **Frontend:** HTML, CSS, vanilla JavaScript, TypeScript API/session modules, and Vite.
- **Backend:** Python, FastAPI, Pydantic, and Uvicorn; HTTPX for Discogs requests.
- **Authentication:** Discogs OAuth via OAuthlib, encrypted credentials via Cryptography.
- **Storage:** SQLite locally or Turso for sessions and response caches, plus a bounded in-memory release cache.
- **Recommendations:** Deterministic metadata scoring; no trained model yet.

## Development checks

From the project root:

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

## Roadmap

- [ ] **Improve candidate selection.** Build an artist/label style-frequency baseline, then evaluate one-vs-rest logistic regression against the current pre-ranker. Keep evaluation releases and alternate editions separate from training data, and compare approaches under the same 30-release enrichment budget, including five exploration slots. Integrate behind a feature flag, preserving the current fallback and actual Discogs styles for final scoring. See the [style pre-ranking proposal](docs/style-pre-ranking.md).
- [ ] **Explore artist and label similarity.** Evaluate shared styles, release eras, and catalogue relationships after establishing the style baseline. Start with simple similarity before testing graph embeddings. See the [artist and label similarity experiment](docs/artist-label-similarity.md).
- [ ] **Measure capacity under load.** Establish supported concurrent usage and tune `MAX_CONCURRENT_SEARCHES` based on observed behavior.

The recommendation experiments are proposals; no model has been trained or integrated.
