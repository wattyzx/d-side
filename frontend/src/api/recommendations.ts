export type Recommendation = {
  listing_id: number;
  release_id: number;
  title: string;
  artists: string[];
  labels: string[];
  year: number | null;
  genres: string[];
  styles: string[];
  price: number;
  currency: string;
  condition: string;
  sleeve_condition: string | null;
  score: number;
  score_breakdown: Record<string, number>;
};

export type StreamEvent = {
  type: string;
  message?: string;

  username?: string;
  seller?: string;

  page?: number;
  pages?: number;
  listings?: number;
  processed?: number;
  candidates?: number;

  recommendation?: Recommendation;

  recommendations?: number;
  has_more?: boolean;
  next_inventory_page_limit?: number;

  [key: string]: unknown;
};

type StreamCallbacks = {
  onEvent?: (event: StreamEvent) => void;
  excludeReleaseIds?: number[];
  inventoryPageLimit?: number;
};

export function sortRecommendations(
  recommendations: Recommendation[],
): Recommendation[] {
  return [...recommendations].sort(
    (a, b) =>
      (b.score_breakdown.total ?? b.score) -
      (a.score_breakdown.total ?? a.score),
  );
}

export async function getRecommendations(
  username: string,
  seller: string,
  callbacks: StreamCallbacks = {},
): Promise<Recommendation[]> {
  const response = await fetch(
    "http://127.0.0.1:8000/recommend/stream",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        username,
        seller,
        exclude_release_ids: callbacks.excludeReleaseIds ?? [],
        inventory_page_limit: callbacks.inventoryPageLimit ?? 10,
      }),
    },
  );

  if (!response.ok) {
    throw new Error(
      `Recommendation request failed: ${response.status}`,
    );
  }

  if (!response.body) {
    throw new Error("Streaming response is not available");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  let buffer = "";
  const recommendations: Recommendation[] = [];

  function handleLine(line: string): boolean {
    if (!line.trim()) return false;
    const event = JSON.parse(line) as StreamEvent;
    callbacks.onEvent?.(event);

    if (event.type === "recommendation" && event.recommendation) {
      recommendations.push(event.recommendation);
    }
    if (event.type === "error") {
      throw new Error(event.message ?? "Recommendation failed");
    }
    return event.type === "done";
  }

  try {
    while (true) {
      const { value, done } = await reader.read();

      if (done) {
        buffer += decoder.decode();
        if (handleLine(buffer)) return sortRecommendations(recommendations);
        throw new Error("Recommendation stream ended before completion");
      }

      buffer += decoder.decode(value, {
        stream: true,
      });

      const lines = buffer.split("\n");

      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (handleLine(line)) {
          return sortRecommendations(recommendations);
        }
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export async function addToWantlist(username: string, releaseId: number): Promise<void> {
  const response = await fetch("http://127.0.0.1:8000/wantlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, release_id: releaseId }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(
      typeof error?.detail === "string"
        ? error.detail
        : "Could not add this record to your wantlist. Please try again.",
    );
  }
}
