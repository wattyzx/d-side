# Style pre-ranking proposal

Status: proposed; no dataset pipeline, trained model, or integration has been implemented.

## Goal

Select more relevant records for full metadata enrichment, especially when an
artist is unfamiliar to the user but its label or other available metadata
suggests a good musical fit. Marketplace summaries provide artist, label, and
year but lack the styles used by the final scorer. A release missed during
candidate selection never reaches that scorer.

The current base pre-score weights artist familiarity at 50%, label familiarity
at 30%, and year at 20%; demand is incorporated afterward. The initial search
selects up to 25 candidates progressively and up to five exploration candidates
after scanning. The proposal adds evidence about likely styles within that same
30-release enrichment budget.

## Approach

### 1. Artist and label style frequencies

Start with an interpretable baseline: count how often each style appears in the
known releases for an artist or label. For example, if 70 of a label's 100
releases include Deep House, its observed Deep House frequency is 70%.
A release can have multiple styles, so these frequencies need not sum to 100%.

Combine available artist and label estimates, smoothing sparse estimates toward
catalogue-wide frequencies. Track supporting release counts and reduce the
influence of weak evidence. Choose smoothing and combination weights on
validation data. Exclude generic entities such as Various and Not On Label.
This gives us a low-complexity reference for deciding whether a trained model
adds value.

### 2. One-vs-rest logistic regression

Train one binary classifier per supported style using artist, label, and year:
House versus releases without a House tag, Techno versus releases without a
Techno tag, and so on. Classifiers predict independently, allowing a release
to receive high predictions for several styles.

Use sparse categorical features for artists and labels, with a year feature or
era buckets and an explicit missing-year indicator. Fit feature encoders only
on training data and handle unknown categories without failing. Start with
styles that have sufficient positive and negative training examples; choose
that support threshold during dataset analysis and report excluded styles.

The output is an estimated probability for each supported style. Model weights
can help explain which features influence a prediction. These estimates are
evidence for candidate selection, not confirmed release metadata or a direct
prediction that a user will like the record.

## Dataset

- Start with collection metadata and cached full release details, then add
  broader catalogue samples. Collection-only data and releases selected by the
  current ranker would reproduce existing coverage gaps.
- Store release ID, master ID where available, artists, labels, year, styles,
  source, and snapshot date. Preserve stable artist and label IDs alongside
  names when available; the current release mapper keeps names only.
- Match training inputs to what marketplace summaries actually expose. Do not
  train using extra credits or other full-release fields unavailable at search
  time. Resolve summary names through local mappings where possible; leave
  ambiguous identities unresolved.
- Deduplicate editions for counting and keep each master release's editions in
  the same training, validation, or test partition. Document the limitations of
  deduplication when master IDs are missing.
- Treat missing style metadata as unknown, rather than an all-negative training
  example. Even populated Discogs style tags can be incomplete or inconsistent.
- Export public release metadata separately from account credentials and
  private user identifiers. Keep collection snapshots used for evaluation
  separate from the catalogue training artifact.

The model learns catalogue style associations. The user's collection supplies
their taste profile at scoring time; unowned records are not dislikes.

## Proposed integration

Train offline and persist the model or frequency tables with their feature
schema, style vocabulary, data snapshot, and version. Search requests should
use local inference without additional Discogs calls for predictions.

For an initial experiment, calculate predicted style affinity as the weighted
average of the user's normalized style preferences, using predicted style
probabilities as weights. If predictions are absent or their sum is zero, use
no bonus. This is a proposed scoring rule to validate, not an existing API.

Add affinity as a bounded bonus to the current pre-score, with its weight and
evidence requirements selected on validation data. Reduce or omit the bonus
when artist/label coverage is poor; year alone offers limited evidence. Preserve
current behavior when the model is disabled, unavailable, or incompatible.

Cache predictions independently of user taste and include the model version in
cache keys. Apply the approach consistently to progressive searches and Search
more, preserving cancellation, duplicate handling, and ownership/wantlist
exclusions. Keep the five exploration slots. Actual Discogs metadata must
continue to drive final scoring and displayed styles.

## Evaluation and rollout

Compare three approaches: the current deterministic ranker, the frequency
baseline, and one-vs-rest logistic regression. Use the same seller inventories,
collection snapshots, page order, and enrichment budget. Reproduce progressive
selection rather than assuming the entire inventory is available from the start.

Fully enrich a manageable evaluation pool, including records the current ranker
would skip. Define a strong-match threshold before the final test, then measure
how many strong full-score matches each approach retrieves within the budget.
Report both selected-match counts and recall against the evaluation pool.
Agreement with the current scorer is a proxy; separately collect user judgments
to assess whether recommendations are useful discoveries.

Report results for familiar and unfamiliar artists/labels, sparse entities,
broad labels, and missing metadata. Distinguish entities unfamiliar to the user
from entities absent from training. Track per-style prediction quality, catalogue
coverage, inference latency, artifact size, and data acquisition costs.
Fit frequency tables, encoders, and models on training data only. Tune parameters

on validation data and reserve the test set for the final comparison. Prevent
evaluation styles and alternate editions from leaking into training features or
aggregate frequencies.

The first milestone is a reproducible dataset and offline comparison report.
Agree on a practical improvement target and latency limit before reviewing test
results. Integrate the winning approach behind a feature flag only if it meets
those criteria without material regressions in the evaluated groups. Keep the
simpler frequency baseline if logistic regression does not improve on it.

## Relationship to node2vec

Style prediction is the first experiment because its inputs, outputs, and
failure cases are easier to inspect. Node2vec learns vectors from catalogue
connections and could later provide a complementary artist/label similarity
signal. It requires graph construction and separate evaluation: connected
entities do not necessarily make similar music, and standard node2vec has no
embedding for entities absent from its training graph.

See the [artist and label similarity experiment](artist-label-similarity.md).
Evaluate graph embeddings after the simpler baseline demonstrates what catalogue
coverage and discovery quality are achievable.

## Reference

[Scikit-learn OneVsRestClassifier documentation](https://scikit-learn.org/stable/modules/generated/sklearn.multiclass.OneVsRestClassifier.html)
describes the multilabel classification strategy proposed for logistic regression.
