import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import {
  addToWantlist,
  getRecommendations,
  sortRecommendations,
  type Recommendation,
  type StreamEvent,
} from "./api/recommendations";

function App() {
  const [username, setUsername] = useState("");
  const [seller, setSeller] = useState("");

  const [recommendations, setRecommendations] = useState<
    Recommendation[]
  >([]);

  const [wantlistRecommendations, setWantlistRecommendations] =
    useState<Recommendation[]>([]);

  const [status, setStatus] = useState("");

  const [activeSearch, setActiveSearch] = useState<{ username: string; seller: string } | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [nextPageLimit, setNextPageLimit] = useState(10);
  const visibleRecommendations = recommendations.filter((record) => record.score > 0.1);

  const recommendationMutation = useMutation({
    mutationFn: (search: {
      username: string;
      seller: string;
      excludeReleaseIds: number[];
      inventoryPageLimit: number;
    }) => getRecommendations(search.username, search.seller, {
      onEvent: handleStreamEvent,
      excludeReleaseIds: search.excludeReleaseIds,
      inventoryPageLimit: search.inventoryPageLimit,
    }),
    onError: () => {
      setStatus("Stopped before completion. Search more to continue.");
    },
  });

  const wantlistMutation = useMutation({
    mutationFn: (record: Recommendation) => addToWantlist(activeSearch!.username, record.release_id),
    onSuccess: (_, record) => {
      setWantlistRecommendations((current) => [...current, record]);
      setRecommendations((current) => current.filter((item) => item.release_id !== record.release_id));
    },
  });

  function handleSearchMore() {
    if (!activeSearch || recommendationMutation.isPending || wantlistMutation.isPending) return;
    setStatus("Searching for more records...");
    recommendationMutation.mutate({
      ...activeSearch,
      excludeReleaseIds: [...recommendations, ...wantlistRecommendations].map((record) => record.release_id),
      inventoryPageLimit: nextPageLimit,
    });
  }

  function handleStreamEvent(event: StreamEvent) {
    if (event.type === "status") {
      setStatus(event.message ?? "");
    }

    if (event.type === "recommendation") {
      if (event.recommendation) {
        setRecommendations((current) =>
          sortRecommendations([
            ...current.filter((item) => item.release_id !== event.recommendation!.release_id),
            event.recommendation!,
          ]),
        );

        setStatus(
          `Scored ${event.processed} of ${event.candidates} recommendations`,
        );
      }
    }

    if (event.type === "progress") {
      setStatus(
        `Reading inventory: page ${event.page} of ${event.pages} (${event.listings} listings)`,
      );
    }

    if (event.type === "pre_rank_complete") {
      setStatus(
        `Scoring ${event.candidates} recommendations`,
      );
    }

    if (event.type === "wantlist") {
      if (event.recommendation) {
        setWantlistRecommendations((current) => [
          ...current.filter((item) => item.release_id !== event.recommendation!.release_id),
          event.recommendation!,
        ]);
      }
    }

    if (event.type === "done") {
      setHasMore(event.has_more ?? false);
      setNextPageLimit(event.next_inventory_page_limit ?? 10);
      setStatus(event.has_more ? "Done — more records available" : "Done — all available records searched");
    }

    if (event.type === "error") {
      setStatus(
        event.message ?? "Something went wrong",
      );
    }
  }

  function handleSubmit(
    event: React.FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();

    if (!username.trim() || !seller.trim()) {
      return;
    }

    if (recommendationMutation.isPending || wantlistMutation.isPending) return;
    const search = { username: username.trim(), seller: seller.trim() };
    setActiveSearch(search);
    setHasMore(true);
    setNextPageLimit(10);
    wantlistMutation.reset();
    setRecommendations([]);
    setWantlistRecommendations([]);
    setStatus("Starting...");

    recommendationMutation.mutate({ ...search, excludeReleaseIds: [], inventoryPageLimit: 10 });
  }

  return (
    <main>
      {/* HERO / SEARCH */}
      <div className="hero">
        <div className="brand">
          <h1 className="logo">D(e)Side</h1>

          <p className="tagline">
            Decide what to dig
          </p>
        </div>

        <form
          className="search-form"
          onSubmit={handleSubmit}
        >
          <div className="field">
            <label htmlFor="username">
              Discogs username
            </label>

            <input
              id="username"
              value={username}
              onChange={(event) =>
                setUsername(event.target.value)
              }
              placeholder="Insert your username"
            />
          </div>

          <div className="field">
            <label htmlFor="seller">
              Seller
            </label>

            <input
              id="seller"
              value={seller}
              onChange={(event) =>
                setSeller(event.target.value)
              }
              placeholder="Insert seller's name"
            />
          </div>

          <button
            className="search-button"
            type="submit"
            disabled={recommendationMutation.isPending || wantlistMutation.isPending}
            aria-busy={recommendationMutation.isPending}
            aria-label={recommendationMutation.isPending ? "Finding records" : undefined}
          >
            <span className="search-button-label">Find records</span>
            {recommendationMutation.isPending && (
              <span className="search-spinner" aria-hidden="true" />
            )}
          </button>
        </form>

        {status && (
          <p
            className="status"
            role="status"
            aria-live="polite"
          >
            {status}
          </p>
        )}

        {recommendationMutation.isError && (
          <p className="error">
            Error: {recommendationMutation.error.message}
          </p>
        )}
      </div>

      <div className="results-layout">
        {wantlistRecommendations.length > 0 && (
          <section className="results wantlist-results">
            <div className="section-header">
              <span>FROM YOUR WANTLIST</span>
              <span>{wantlistRecommendations.length}</span>
            </div>
            <div className="record-list">
              {wantlistRecommendations.map((recommendation) => (
                <RecordRow
                  key={`want-${recommendation.listing_id}`}
                  recommendation={recommendation}
                />
              ))}
            </div>
          </section>
        )}

        {activeSearch && (
          <section className="results recommendation-results">
            <div className="section-header">
              <span>RECOMMENDATIONS</span>
              <span>{visibleRecommendations.length}</span>
            </div>
            <div className="record-list">
              {visibleRecommendations.map((recommendation, index) => (
                <RecordRow
                  key={recommendation.listing_id}
                  recommendation={recommendation}
                  rank={index + 1}
                  onAdd={() => wantlistMutation.mutate(recommendation)}
                  canAdd={!recommendationMutation.isPending && !wantlistMutation.isPending}
                  isAdding={wantlistMutation.isPending && wantlistMutation.variables?.release_id === recommendation.release_id}
                  addError={wantlistMutation.isError && wantlistMutation.variables?.release_id === recommendation.release_id
                    ? wantlistMutation.error.message : undefined}
                />
              ))}
            </div>
            {!recommendationMutation.isPending && visibleRecommendations.length === 0 && (
              <p className="status">No recommendations above 0.1 found so far.</p>
            )}
            <button
              className="search-more-button"
              type="button"
              disabled={!hasMore || recommendationMutation.isPending || wantlistMutation.isPending}
              onClick={handleSearchMore}
            >
              {recommendationMutation.isPending ? "Searching..." : hasMore ? "Search more" : "No more records"}
            </button>
          </section>
        )}
      </div>
    </main>
  );
}

function RecordRow({
  recommendation,
  rank,
  onAdd,
  canAdd,
  isAdding,
  addError,
}: {
  recommendation: Recommendation;
  rank?: number;
  onAdd?: () => void;
  canAdd?: boolean;
  isAdding?: boolean;
  addError?: string;
}) {
  const title = `${recommendation.artists.join(", ")} — ${recommendation.title}`;
  const metadata = [
    recommendation.labels.join(", "),
    recommendation.styles.join(", "),
    recommendation.condition,
  ].filter(Boolean).join(" · ");

  return (
    <article className="record-row">
      <div className="record-heading">
        {rank !== undefined && (
          <span className="record-rank">#{String(rank).padStart(2, "0")}</span>
        )}
        <h3 title={title}>{title}</h3>
        <span className="price">
          {recommendation.price} {recommendation.currency === "EUR" ? "€" : recommendation.currency}
        </span>
      </div>
      <div className="record-details">
        <p className="record-meta" title={metadata}>{metadata}</p>
        {rank !== undefined && (
          <span className="score">Score {recommendation.score.toFixed(3)}</span>
        )}
        <div className="discogs-links">
          <a
            href={`https://www.discogs.com/release/${recommendation.release_id}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            Release ↗
          </a>
          <a
            href={`https://www.discogs.com/sell/item/${recommendation.listing_id}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            Listing ↗
          </a>
          {onAdd && (
            <button
              className="wantlist-button"
              type="button"
              onClick={onAdd}
              disabled={!canAdd}
              aria-label={`Add ${title} to wantlist`}
            >
              {isAdding ? "Adding..." : "+ Wantlist"}
            </button>
          )}
        </div>
      </div>
      {addError && <p className="record-error" role="alert">{addError}</p>}
    </article>
  );
}

export default App;
