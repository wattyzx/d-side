import { session } from "../session.ts";
import { apiFetch, assertCurrentSession } from "./http.ts";

export type Recommendation = {
  listing_id: number;
  release_id: number;
  title: string;
  thumbnail_url?: string | null;
  artists: string[];
  labels: string[];
  year: number | null;
  genres: string[];
  styles: string[];
  price: number;
  currency: string;
  condition: string;
  sleeve_condition: string | null;
  community_want?: number | null;
  community_have?: number | null;
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
  inventory_scanning?: boolean;

  recommendation?: Recommendation;

  recommendations?: number;
  has_more?: boolean;
  inventory_truncated?: boolean;
  reported_pages?: number;

  [key: string]: unknown;
};

type StreamCallbacks = {
  onEvent?: (event: StreamEvent) => void;
  excludeReleaseIds?: number[];
  searchId?: string;
  signal?: AbortSignal;
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
  seller: string,
  callbacks: StreamCallbacks = {},
): Promise<Recommendation[]> {
  const revision = session.getSnapshot().revision;
  const response = await apiFetch(
    "/recommend/stream",
    {
      method: "POST",
      signal: callbacks.signal,
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        seller,
        exclude_release_ids: callbacks.excludeReleaseIds ?? [],
        ...(callbacks.searchId ? { search_id: callbacks.searchId } : {}),
      }),
    },
    { fallback: "Could not find recommendations. Please try again." },
  );

  if (!response.body) {
    throw new Error("Streaming response is not available");
  }

  const reader = response.body.getReader();
  const cancelReader = () => { void reader.cancel().catch(() => {}); };
  callbacks.signal?.addEventListener("abort", cancelReader, { once: true });
  if (callbacks.signal?.aborted) cancelReader();
  const decoder = new TextDecoder();

  let buffer = "";
  const recommendations: Recommendation[] = [];

  function handleLine(line: string): boolean {
    assertCurrentSession(revision);
    callbacks.signal?.throwIfAborted();
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
  } catch (error) {
    assertCurrentSession(revision);
    throw error;
  } finally {
    callbacks.signal?.removeEventListener("abort", cancelReader);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export async function cancelSearch(searchId: string): Promise<void> {
  await apiFetch("/recommend/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ search_id: searchId }),
  }, { fallback: "Could not confirm cancellation. Please try again." });
}

export async function addToWantlist(releaseId: number): Promise<void> {
  await apiFetch("/wantlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ release_id: releaseId }),
  }, { fallback: "Could not add this record to your wantlist. Please try again." });
}
