# D(e)Side

> **Decide what to dig.**


D(e)Side helps you find the records most likely to match your taste inside a Discogs seller's inventory.
It uses user's personal music taste and his own record collection to find and rank the best matches inside a discogs seller marketplace.

## Idea

The user's taste is analyzed from:

- their Discogs collection
- artists, releases or tracks they explicitly like
- natural language preferences, for example:
  - "early 2000s minimal"
  - "deep and hypnotic house"
  - "music similar to Perlon releases"

## Development approach

The first version will use only Discogs metadata and deterministic similarity
rules.
Later versions may introduce:
- embeddings
- machine learning
- natural language preference parsing
- user feedback
- learning ranking techniques

## Initial data

Discogs' metadata useful for the project:
- artist
- title
- year
- genres
- styles
- labels
- formats
- catalogue numbers
The first goal is to transform Discogs API responses into a clean internal
representation of a release.

## Recommendation approach
The first recommender will compare a user's taste profile with the metadata of
each release available in a seller's inventory.
For example, the system may consider:
- similarity between genres
- similarity between styles
- recurring artists
- recurring labels
- release years
- formats
- overlap with the user's collection
Each candidate release will receive a score.
The seller's inventory can then be ranked according to that score.

## Known limitation: candidate generation

The current lightweight pre-ranking stage uses metadata already available in
Discogs Marketplace listings, mainly:

- artist
- label
- year

However, the most discriminating recommendation signal observed so far is
`style`, which is not included in Marketplace listing summaries.

This creates an important candidate problem: not including significant record that wuold perform on the final score system.

### Possible Fix

Preference prototypes: derive a small set of representative record profiles from the user's collection, then retrieve and rank seller records according to their similarity to one or more prototypes rather than relying only on a single global taste profile.

## Roadmap
### Phase 1 — Discogs data
- Define a Release model X
- Connect to the Discogs API X
- Retrieve a release by ID X
- Retrieve a user's collection X
- Retrieve a seller's inventory X
### Phase 2 — Baseline recommender
- Build a user taste profile X
- Compare metadata X
- Compute similarity scores X
- Rank seller releases X
### Phase 3 — Semantic recommendations
- Convert musical metadata and preferences into embeddings
- Measure semantic similarity
- Combine semantic and metadata scores
### Phase 4 — Learning
- Collect positive and negative feedback
- Learn user-specific preferences
- Experiment with recommendation and ranking models

## How does it work

```text
User collection
       │
       ├──────────────┐
       │              │
    Explicit preferences 
       │              │
       └──────┬───────┘
              ↓
        User Taste

              +

      Seller Inventory
              ↓
        Recommendation
              ↓
         Ranked Releases
```
## Better engine option

The engine may combine metadata such as years and styles. 
Using recourring years of particular style, may have a better understandig of the user'style. 
To do so building proto type or selecting rappresentative records in the collection could be useful.