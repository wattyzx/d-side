import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import {
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

  const recommendationMutation = useMutation({
    mutationFn: () =>
      getRecommendations(username, seller, {
        onEvent: handleStreamEvent,
      }),

    onSuccess: (data) => {
      setRecommendations(data);
      setStatus("Done");
    },
    onError: () => {
      setStatus("Stopped before completion");
    },
  });

  function handleStreamEvent(event: StreamEvent) {
    if (event.type === "status") {
      setStatus(event.message ?? "");
    }

    if (event.type === "recommendation") {
      if (event.recommendation) {
        setRecommendations((current) => sortRecommendations([
          ...current,
          event.recommendation!,
        ]));
        setStatus(`Scored ${event.processed} of ${event.candidates} recommendations`);
      }
    }

    if (event.type === "progress") {
      setStatus(`Reading inventory: page ${event.page} of ${event.pages} (${event.listings} listings)`);
    }

    if (event.type === "pre_rank_complete") {
      setStatus(`Scoring ${event.candidates} recommendations`);
    }

    if (event.type === "wantlist") {
      if (event.recommendation) {
        setWantlistRecommendations((current) => [
          ...current,
          event.recommendation!,
        ]);
      }
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

    setRecommendations([]);
    setWantlistRecommendations([]);
    setStatus("Starting...");

    recommendationMutation.mutate();
  }

  return (
    <main>
      <h1>D(e)Side</h1>

      <p>Decide what to dig</p>

      <form onSubmit={handleSubmit}>
        <div>
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

        <div>
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
          type="submit"
          disabled={recommendationMutation.isPending}
        >
          {recommendationMutation.isPending
            ? "Finding records..."
            : "Find records"}
        </button>
      </form>

      {status && (
        <p role="status" aria-live="polite">
          {status}
        </p>
      )}

      {recommendationMutation.isError && (
        <p>
          Error: {recommendationMutation.error.message}
        </p>
      )}

      {wantlistRecommendations.length > 0 && (
        <section>
          <h2>Wantlist matches</h2>

          {wantlistRecommendations.map(
            (recommendation) => (
              <article
                key={`want-${recommendation.listing_id}`}
              >
                <h3>
                  {recommendation.title}
                </h3>

                <p>
                  {recommendation.artists.join(", ")}
                </p>

                <p>
                  {recommendation.labels.join(", ")}
                </p>

                <p>
                  {recommendation.styles.join(" · ")}
                </p>

                <p>
                  {recommendation.price}{" "}
                  {recommendation.currency}
                </p>

                <DiscogsLinks recommendation={recommendation} />
              </article>
            ),
          )}
        </section>
      )}

      {recommendations.length > 0 && (
        <section>
          <h2>Recommendations</h2>

          {recommendations.map(
            (recommendation) => (
              <article
                key={recommendation.listing_id}
              >
                <h3>
                  {recommendation.title}
                </h3>

                <p>
                  {recommendation.artists.join(", ")}
                </p>

                <p>
                  {recommendation.labels.join(", ")}
                </p>

                <p>
                  {recommendation.styles.join(" · ")}
                </p>

                <p>
                  {recommendation.price}{" "}
                  {recommendation.currency}
                </p>

                <DiscogsLinks recommendation={recommendation} />

                <strong>
                  Score:{" "}
                  {recommendation.score.toFixed(3)}
                </strong>
              </article>
            ),
          )}
        </section>
      )}
    </main>
  );
}

function DiscogsLinks({ recommendation }: { recommendation: Recommendation }) {
  return (
    <p>
      <a
        href={`https://www.discogs.com/release/${recommendation.release_id}`}
        target="_blank"
        rel="noopener noreferrer"
      >
        View release on Discogs
      </a>
      {" · "}
      <a
        href={`https://www.discogs.com/sell/item/${recommendation.listing_id}`}
        target="_blank"
        rel="noopener noreferrer"
      >
        View seller listing
      </a>
    </p>
  );
}

export default App;
