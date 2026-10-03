# D(e)Side

**Decide what to dig.**

D(e)Side helps you find records you might like in a Discogs seller’s inventory.
It uses your collection to suggest what to check out next.
Wantlist matches appear as the inventory is scanned, and recommendations appear
as they are scored.
You can open each record on Discogs or add it straight to your wantlist.

## How it works

Each search scans up to 100 pages of the seller’s inventory and shows wantlist
matches as they’re found. It selects up to 25 promising records based on artist,
label, year, and demand, plus up to 5 from
across the remaining list to give less obvious matches a chance.
It then loads their full details and scores them against your collection,
mainly using musical styles. Only recommendations scoring above 0.1 are shown;
wantlist matches are shown regardless of score. Records you already own
are skipped.

**Search more** scores another batch of unseen records from the scanned inventory.
Results arrive as they’re scored, and Discogs responses are cached to speed up
later searches. Large inventories take longer to scan on the first search;
progress shows the current page and the total page count.

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

Create a `.env` file in that folder with your Discogs personal access token:

```env
DISCOGS_TOKEN=your_token_here
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

Open **http://localhost:5173**. To save records to your wantlist, the configured
token must belong to the username you searched for.

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

## Known limitation: candidate generation
The current lightweight pre-ranking stage uses metadata already available in Discogs Marketplace listings, mainly:

- artist
- label
- year

The full scoring stage relies mainly on musical styles, which are not included
in Marketplace listing summaries. As a result, pre-ranking can miss records
that would score well once their full metadata is loaded.

## What’s next

Planned improvements include Discogs login so each person can connect their own
account, and better candidate selection to find matches that pre-ranking might
miss. The current version uses Discogs metadata and a deterministic scoring
formula.

One possible direction is to model styles and release years together, capturing
preferences for particular years within a style. Representative records or
clusters from the collection could help describe those preferences.
