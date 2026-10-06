import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import AccountControls from "./AccountControls";
import { getAccount } from "./api/auth";
import { accountQueryKey, session } from "./session";

import {
  addToWantlist,
  cancelSearch,
  getRecommendations,
  sortRecommendations,
  type Recommendation,
  type StreamEvent,
} from "./api/recommendations";

function App() {
  const snapshot = useSyncExternalStore(session.subscribe, session.getSnapshot);
  // Unmount account-specific state and callbacks whenever a session ends.
  return <RecommendationApp key={snapshot.revision} sessionExpired={snapshot.expired} />;
}

function RecommendationApp({ sessionExpired }: { sessionExpired: boolean }) {
  const account = useQuery({ queryKey: accountQueryKey, queryFn: getAccount, retry: false });
  const username = account.data?.username ?? "";
  const [seller, setSeller] = useState("");
  const activeRequest = useRef<{ id: string; controller: AbortController } | null>(null);
  const cancelling = useRef(false);
  useEffect(() => () => { activeRequest.current?.controller.abort(); }, []);

  const [recommendations, setRecommendations] = useState<
    Recommendation[]
  >([]);

  const [wantlistRecommendations, setWantlistRecommendations] =
    useState<Recommendation[]>([]);

  const [status, setStatus] = useState("");

  const [activeSearch, setActiveSearch] = useState<{ username: string; seller: string } | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [inventoryNotice, setInventoryNotice] = useState("");
  const visibleRecommendations = recommendations.filter((record) => record.score > 0.1);

  const recommendationMutation = useMutation({
    mutationFn: (search: {
      username: string;
      seller: string;
      excludeReleaseIds: number[];
      searchId: string;
      signal: AbortSignal;
    }) => getRecommendations(search.seller, {
      onEvent: handleStreamEvent,
      excludeReleaseIds: search.excludeReleaseIds,
      searchId: search.searchId,
      signal: search.signal,
    }),
    onError: (_, search) => {
      if (search.signal.aborted) return;
      setStatus("Stopped before completion. Search more to continue.");
    },
    onSettled: (_, __, search) => {
      if (!cancelling.current && activeRequest.current?.id === search.searchId) {
        activeRequest.current = null;
      }
    },
  });

  const cancelMutation = useMutation({
    mutationFn: cancelSearch,
    onSuccess: () => { setStatus("Search cancelled. Search more to continue."); },
    onError: () => { setStatus("Could not confirm cancellation. Wait a moment before searching again."); },
    onSettled: () => {
      cancelling.current = false;
      activeRequest.current = null;
    },
  });

  function startSearch(search: { username: string; seller: string }, excludeReleaseIds: number[]) {
    // Reserve immediately rather than waiting for React's pending-state render.
    if (activeRequest.current || cancelling.current) return;
    const request = { id: crypto.randomUUID(), controller: new AbortController() };
    activeRequest.current = request;
    recommendationMutation.mutate({ ...search, excludeReleaseIds, searchId: request.id,
      signal: request.controller.signal });
  }

  function handleCancel() {
    const request = activeRequest.current;
    if (!request || cancelling.current) return;
    cancelling.current = true;
    setStatus("Cancelling search…");
    request.controller.abort();
    cancelMutation.mutate(request.id);
  }

  const wantlistMutation = useMutation({
    mutationFn: (record: Recommendation) => addToWantlist(record.release_id),
    onSuccess: (_, record) => {
      setWantlistRecommendations((current) => [...current, record]);
      setRecommendations((current) => current.filter((item) => item.release_id !== record.release_id));
    },
  });

  function handleSearchMore() {
    if (!username || activeSearch?.username !== username || activeRequest.current || cancelling.current || wantlistMutation.isPending) return;
    setStatus("Searching for more records...");
    startSearch(activeSearch, [...recommendations, ...wantlistRecommendations].map((record) => record.release_id));
  }

  function handleStreamEvent(event: StreamEvent) {
    if (event.type === "start") {
      setInventoryNotice(event.inventory_truncated
        ? `Discogs only allows access to the first 100 of this seller’s ${event.reported_pages} inventory pages. Wantlist matches and recommendations cover those pages; records beyond them may be missing.`
        : "");
    }
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
          event.inventory_scanning
            ? `Scored ${event.processed} recommendations — continuing inventory scan`
            : `Scored ${event.processed} of ${event.candidates} recommendations`,
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
      setStatus(event.has_more
        ? "Done — more records available"
        : event.inventory_truncated
          ? "Done — all accessible records searched"
          : "Done — all available records searched");
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

    if (activeRequest.current || cancelling.current || wantlistMutation.isPending) return;
    const search = { username: username.trim(), seller: seller.trim() };
    setActiveSearch(search);
    setHasMore(true);
    setInventoryNotice("");
    wantlistMutation.reset();
    setRecommendations([]);
    setWantlistRecommendations([]);
    setStatus("Starting...");

    startSearch(search, []);
  }

  return (
    <main>
      <AccountControls
        account={account}
        busy={recommendationMutation.isPending || cancelMutation.isPending || wantlistMutation.isPending}
        sessionExpired={sessionExpired}
      />
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

          <div className="search-actions">
            <button
              className="search-button"
              type="submit"
              disabled={!username || recommendationMutation.isPending || cancelMutation.isPending || wantlistMutation.isPending}
              aria-busy={recommendationMutation.isPending}
              aria-label={recommendationMutation.isPending ? "Finding records" : undefined}
            >
              <span className="search-button-label">Find records</span>
              {recommendationMutation.isPending && (
                <span className="search-spinner" aria-hidden="true" />
              )}
            </button>
            {(recommendationMutation.isPending || cancelMutation.isPending) && (
              <button className="cancel-search-button" type="button" onClick={handleCancel}
                disabled={cancelMutation.isPending}>
                {cancelMutation.isPending ? "Cancelling…" : "Cancel search"}
              </button>
            )}
          </div>
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

        {inventoryNotice && <p className="status">{inventoryNotice}</p>}

        {recommendationMutation.isError && !recommendationMutation.variables?.signal.aborted && (
          <p className="error">
            Error: {recommendationMutation.error.message}
          </p>
        )}
      </div>

      <div className="results-layout">
        {username && activeSearch?.username === username && wantlistRecommendations.length > 0 && (
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

        {username && activeSearch?.username === username && (
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
                  canAdd={!!username && !recommendationMutation.isPending && !cancelMutation.isPending && !wantlistMutation.isPending}
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
              disabled={!hasMore || recommendationMutation.isPending || cancelMutation.isPending || wantlistMutation.isPending}
              onClick={handleSearchMore}
            >
              {recommendationMutation.isPending ? "Searching..." : hasMore ? "Search more" : inventoryNotice ? "No more accessible records" : "No more records"}
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
