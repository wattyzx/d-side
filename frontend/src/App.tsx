import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { getRecommendations } from "./api/recommendations";

function App() {
  const [username, setUsername] = useState("");
  const [seller, setSeller] = useState("");

  const recommendationMutation = useMutation({
    mutationFn: () =>
      getRecommendations(username, seller),
  });

  function handleSubmit(
    event: React.FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();

    if (!username.trim() || !seller.trim()) {
      return;
    }

    recommendationMutation.mutate();
  }

  return (
    <main>
      <h1>D(e)Side</h1>

      <p>decide what to dig</p>

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
            placeholder="watt.ia"
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
            placeholder="AKER_RECORDS"
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

      {recommendationMutation.isError && (
        <p>
          Error: {recommendationMutation.error.message}
        </p>
      )}

      {recommendationMutation.data && (
        <section>
          <h2>Recommendations</h2>

          {recommendationMutation.data.recommendations.map(
            (recommendation) => (
              <article key={recommendation.listing_id}>
                <h3>{recommendation.title}</h3>

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

export default App;