# D(e)Side

**Decide what to dig.**

D(e)Side helps you find records you might like in a Discogs seller’s inventory.
It uses your collection tosuggest what to check out next.
Your wantlist matches appear immediatly while the suggestions are displayed as they come
You can open each record on Discogs or add it straight to your wantlist.

## How it works

Each search reads all accessible pages of the seller’s inventory and shows wantlist
matches as they’re found. It picks
25 promising records based on artist, label, year, and demand, plus 5 from
across the remaining list to give less obvious matches a chance.
It then loads their full details and scores them against your collection,
mainly using musical styles. Recommendations scoring below 0.1 are not shown;
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
The first recommender will compare a user's taste profile with the metadata of each release available in a seller's inventory. For example, the system may consider:

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

## Known limitation: candidate generation
The current lightweight pre-ranking stage uses metadata already available in Discogs Marketplace listings, mainly:

- artist
- label
- year

However, the most discriminating recommendation signal observed so far is style, which is not included in Marketplace listing summaries.

## What’s next

Discogs login so each person can connect their own account, and better ways to
find matches that the first ranking might miss. This version uses Discogs
metadata and a scoring formula.

**Better engine option**
The engine may combine metadata such as years and styles. Using recourring years of particular style, may have a better understandig of the user'style. To do so building prototypes or selecting rappresentative records in the collection could be useful.
