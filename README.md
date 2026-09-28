# B-Side

B-Side is a music recommendation engine for Discogs marketplace.
It uses user's personal music taste and his own record collection to find and rank the best matches inside a discogs seller marketplace.

## Idea

The user's taste can be inferred from:

- their Discogs collection;
- artists, releases or tracks they explicitly like;
- natural-language preferences, for example:
  - "early 2000s minimal"
  - "deep and hypnotic house"
  - "music similar to Perlon releases"

## Development approach

The first version will use only Discogs metadata and deterministic similarity
rules.
Later versions may introduce:
- embeddings;
- machine learning;
- natural-language preference parsing;
- user feedback;
- learning-to-rank techniques.

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
- similarity between genres;
- similarity between styles;
- recurring artists;
- recurring labels;
- release years;
- formats;
- overlap with the user's collection.
Each candidate release will receive a score.
The seller's inventory can then be ranked according to that score.

## Roadmap
### Phase 1 — Discogs data
- Define a Release model
- Connect to the Discogs API
- Retrieve a release by ID
- Retrieve a user's collection
- Retrieve a seller's inventory
### Phase 2 — Baseline recommender
- Build a user taste profile
- Compare metadata
- Compute similarity scores
- Rank seller releases
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
        Taste Profile

              +

      Seller Inventory
              ↓
        Recommendation
              ↓
         Ranked Releases
```