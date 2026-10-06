# Artist and label similarity experiment

Status: proposed; no model has been trained or integrated.

## Goal

Improve candidate selection when a seller's artist or label does not appear in
the user's collection but is related to their taste. Marketplace summaries
provide artist, label, and year, while the styles used by full scoring require
release enrichment. Cached artist and label relationships could help choose
better candidates before spending those requests.

## Data

Start with collection metadata and cached release details. Broader catalogue
samples will be needed to cover artists and labels absent from the collection.
Preserve Discogs artist and label IDs alongside names in the internal release
model; the current mapper keeps names only. Marketplace summary names will need
a cached mapping to entities, with ambiguous names left unresolved.

Useful evidence includes:

- Artists credited on releases and the labels issuing them.
- Styles and release eras associated with each artist and label.
- Explicit artist aliases and label parent/sublabel relationships, where available.

Deduplicate release versions where possible so repeated editions do not inflate
evidence. Exclude generic entities such as Various and Not On Label. Track
coverage and supporting release counts; one shared artist or a corporate label
relationship is weak evidence of musical similarity.

## Approaches to compare

1. Keep the current deterministic pre-ranker as the reference.
2. Build a simple similarity baseline from style/year profiles and shared artists
   or labels. Normalize overlap so large catalogues do not dominate, and reduce
   confidence when supporting data is sparse.
3. Train graph embeddings on artist–release–label connections, optionally adding
   styles, eras, and explicit relationships. Node2vec is one candidate to test;
   graph proximity must be evaluated as a musical relevance signal.

The user's collection defines their preferences; the broader catalogue supplies
relationship knowledge. This experiment learns related entities, rather than
learning personal likes and dislikes. A later feedback-trained ranker would
need logged impressions and preference signals. Unowned records are unknown,
not automatic dislikes.

## Integration

Build similarities or embeddings separately from search requests and persist
them with a model version and data snapshot. Pre-ranking should use local cached
lookups to add a bounded similarity bonus, weaker than direct artist/label
matches. Missing or ambiguous entities should retain the existing score.

Keep full release scoring based on actual Discogs metadata during the experiment.
Retain exploration candidates to give records outside known relationships a chance.

## Evaluation

Compare approaches on the same seller inventories, collection snapshots, page
order, and enrichment request budget, including the current progressive selection
behavior. Fully enrich a manageable evaluation pool to measure how many strong
full-score matches each approach selects. This measures agreement with the
current scorer; separately assess usefulness through user judgments or feedback.

Use held-out releases and prevent their metadata or alternate editions from
leaking into the training data when testing generalization. Include unfamiliar
artists/labels, sparse catalogues, and broad labels. Record candidate recall,
entity coverage, lookup latency, and catalogue enrichment costs.

Integrate trained embeddings only if they improve on the simpler baseline.

## Reference

[Node2vec research and implementation](https://snap.stanford.edu/node2vec/)
describes learning representations from network structure.
