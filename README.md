# D(e)Side

**Decide what to dig.**

D(e)Side helps you find records you might like in a Discogs seller’s inventory.
It uses your collection to suggest what to check out next.
Wantlist matches appear as the inventory is scanned, and recommendations appear
as they are scored.
You can open each record on Discogs or add it straight to your wantlist.

## How it works

Each search scans up to 100 pages of the seller’s inventory. Recommendations
start arriving from the first page with eligible records. As the scan progresses, it selects up to 25 promising
records based on artist, label, year, and demand. After reaching the last page,
it selects up to 5 from across the remaining list to give less obvious matches
a chance. Early selections use the inventory scanned so far, so they can differ
from the top candidates of a complete inventory scan.
It then loads their full details and scores them against your collection,
mainly using musical styles. Only recommendations scoring above 0.1 are shown;
wantlist matches are shown regardless of score. Records you already own
are skipped.

**Search more** scores another batch of unseen records from the scanned inventory.
Results arrive as they’re scored, and Discogs responses are cached to speed up
later searches. Large inventories take longer to scan on the first search;
progress shows the current page and the total page count.

**Cancel search** stops the current scan and retains results already received.
The button shows **Cancelling…** until the backend worker exits; then **Search
more** can continue with unseen releases. Closing the connection also cancels
the backend scan. A Discogs HTTP request already in flight finishes or times out,
but cancellation prevents subsequent requests and interrupts pacing/retry waits.

Only one search can run per Discogs account, including across browser tabs.
Additional searches receive an HTTP 409 response. Cancellation uses a unique
search ID so a delayed cancel request cannot stop a newer scan.
Across accounts, at most four searches can run at once by default, configurable
with `MAX_CONCURRENT_SEARCHES`. When all slots are occupied, new searches receive
HTTP 503 with `Retry-After: 5`. Search work uses a separate worker limiter so
waiting scans do not exhaust the workers used by health checks, login, and
cancellation. A cancelled search keeps its slot until its worker exits.
This limit is process-local: use **one backend instance and one Uvicorn worker**
until admission and cancellation state are stored in a shared service.

Discogs blocks pages above 100 for inventories other than your own. At 100
listings per page, this limits the scan to 10,000 listings per seller. For
larger sellers, the app shows a notice: wantlist matches and recommendations
are incomplete, and **Search more** only scores remaining records within the
accessible pages.

## Recommendation approach

The recommender builds a taste profile from your collection and compares it with
release metadata. It uses:

- genres
- styles
- recurring artists
- recurring labels
- release years

## Run locally

You’ll need Python 3.10+ and Node.js 22.12+.

From the project folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Register a Discogs application and create a `.env` file in that folder with
its consumer credentials:

```env
DISCOGS_CONSUMER_KEY=your_key_here
DISCOGS_CONSUMER_SECRET=your_secret_here
AUTH_ENCRYPTION_KEY=your_generated_key_here
```

Install the frontend dependencies once:

```sh
npm install --prefix frontend
```

Then start both the backend and frontend with one command from the project folder:

```sh
./run.sh
```

Press **Ctrl+C** to stop both servers. The command uses `.venv` automatically,
so you don’t need to activate it each time.

Open **http://localhost:5173**, connect your Discogs account, and enter a seller.
Searches use your signed-in account's collection and wantlist; saves go to your own wantlist. No separate username or personal access token is needed.

## Discogs login

The frontend provides **Connect with Discogs**, the connected username, and
**Sign out**, backed by OAuth login and persistent sessions. The recommendation and wantlist routes derive the account from the session and use
that account's OAuth credentials. Personal response caches are separated by account. Public release metadata can still be shared between accounts.

Relative database paths resolve from the project folder. Cookies remain
HttpOnly with `SameSite=Lax`. Secure cookies cannot be disabled for HTTPS callbacks. Invalid URLs, encryption keys, and durations are rejected; missing
login credentials leave login unavailable while the health endpoint still works.
Restart the backend after changing settings.

Expired response-cache rows and auth records are removed at startup and every
cleanup interval, including when the app is idle. SQLite connections close
after each operation, and WAL mode allows readers alongside writers. Ordinary
session checks take no write lock; consuming OAuth tokens remains atomic.
The release metadata cache uses a size limit, TTL, and least-recently-used eviction.
Deleting expired SQLite rows makes space reusable; it does not necessarily
shrink the database file.

Discogs requests share a conservative rate cap. Eligible queued requests take
turns, while extra caller delays and transient-error retries apply to that
account. HTTP 429 cooldowns and exhausted reported budgets remain shared;
reported lower rate limits slow the queue. Separate OAuth accounts are not
treated as permission to exceed a shared upstream budget.
Rate-limit feedback from completed requests is recorded even when their search
was cancelled in flight, so subsequent requests still respect the cooldown.

The default local callback is
`http://localhost:5173/auth/discogs/callback`, which is also sent during the
request-token step. HTTPS is required for non-local login URLs.

Start both servers with `./run.sh`, open **http://localhost:5173**, click
**Connect with Discogs**, and authorize D(e)Side. The callback returns you to
the app, which displays your username. Refresh to verify the session survives;
click **Sign out** to end it. Failed callbacks return to the app with an error.
If a request reports an expired session, the frontend clears the account and
results, stops processing requests from that session, and asks you to reconnect.
Opening the app while signed out shows the login button without an expiry warning.
Vite proxies `/auth` to FastAPI so local cookies share the frontend hostname.
Use `localhost:5173` consistently and restart Vite after configuration changes.
If you previously set `DISCOGS_CALLBACK_URL`, update it to the URL above.

Pending logins expire after ten minutes and can be exchanged only once by the
browser that started them. Sessions expire after seven days. The browser gets
an HttpOnly session cookie; credentials stay encrypted in `data/auth.sqlite3`,
separate from the disposable cache. Logout deletes the local session and its
credentials; it does not revoke the application's authorization at Discogs.

OAuth integration follows the [Discogs Python client's handshake and signing implementation](https://github.com/joalla/discogs_client).

## Run tests

From the project folder, run the Python tests with the standard-library
`unittest` runner:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Run the frontend tests, build, and lint checks with:

```sh
npm test --prefix frontend
npm run build --prefix frontend
npm run lint --prefix frontend
```

The automated tests use mocked Discogs responses and do not require a live token.

## Planned deployment

The recommended starting point is a private prototype on Render's free tier
with a persistent remote cache on Turso.

The proposed setup for an initial hosted prototype is:

- **Frontend:** React static site on Render's free tier.
- **Backend:** FastAPI web service on Render's free tier.
- **Database:** Turso's free tier, using a SQLite compatible remote database to preserve cached Discogs responses when the backend sleeps or restarts.

## Known limitation: candidate generation
The current lightweight pre-ranking stage uses metadata already available in Discogs Marketplace listings, mainly:

- artist
- label
- year

The full scoring stage relies mainly on musical styles, which are not included
in Marketplace listing summaries. As a result, pre-ranking can miss records
that would score well once their full metadata is loaded.

## TODO

Code review fixes to complete before public deployment, in priority order:

- [x] **1. High — Keep searches from blocking other endpoints.** Added a shared
  admission limit and a separate search worker limiter. Regression tests verify
  that health checks, login, and cancellation remain responsive with search
  capacity fully occupied, and that slots remain held until workers exit.
- [x] **2. Medium — Reduce repeated ranking work.** Preference lookups are
  prepared once per search, and base listing scores are reused across pages.
  Demand normalization still reflects the accumulated inventory; sorting is
  skipped when the current page has no scoring budget. Added cancellation
  checks during preparation and ranking, regression tests for incremental
  scores and duplicate listings, and a large-inventory benchmark. Existing
  scoring and candidate selection behavior is preserved.
- [x] **3. Medium — Preserve rate-limit feedback when cancelling.** Response
  rate-limit headers and HTTP 429 cooldowns are recorded before checking
  cancellation. Regression tests verify that cancelled requests do not retry
  and that subsequent requests from another account respect the shared budget.
- [x] **4. Medium — Prevent stale wantlist cache writes after a save.** Saves
  advance a namespace version atomically with cache invalidation; fetches only
  cache their response if that version still matches. Regression tests cover
  overlapping fetches and saves, preservation of newer cached responses, and
  version persistence and isolation across accounts.

## What’s next

Planned improvements include hosted deployment and better candidate selection
to find matches that pre-ranking might miss. The current version uses Discogs
metadata and a deterministic scoring
formula.

**Style pre-ranking:** Explore predicting likely musical styles from artist, label, and release year using releases with known styles. Compare this approach with the current pre-ranker to see whether it selects better candidates within the same request budget. Final scoring would continue to use actual Discogs styles.

**Artist and label similarity:** Explore links between artists and labels using
shared styles, release eras, and catalogue relationships. Start with a simple
similarity baseline, then test trained graph embeddings as a way to give
unfamiliar but related names a small pre-ranking bonus. This experiment is not
implemented yet; see the [experiment plan](docs/artist-label-similarity.md).
