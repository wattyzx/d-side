# D(e)Side

**Decide what to dig.**

D(e)Side helps you find records you might like in a Discogs seller’s inventory.
It uses your collection tosuggest what to check out next.
Your wantlist matches appear immediatly while the suggestions are displayed as they come
You can open each record on Discogs or add it straight to your wantlist.

## How it works

The first search reads up to 10 inventory pages (1,000 listings). It picks
25 promising records based on artist, label, year, and demand, plus 5 from
across the remaining list to give less obvious matches a chance.
It then loads their full details and scores them against your collection,
mainly using musical styles. Recommendations scoring below 0.1 are not shown;
wantlist matches are shown regardless of score. Records you already own
are skipped.

**Search more** checks another batch of unseen records. Once the current pages
are exhausted, it reads up to 10 more pages. Results arrive as they’re scored,
and Discogs responses are cached to speed up later searches.


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

Start the backend:

```sh
uvicorn app.api:app --reload
```

In another terminal, start the frontend:

```sh
cd frontend
npm install
npm run dev
```

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