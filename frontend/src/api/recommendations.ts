import type { RecommendationResponse } from "../types/recommendation";

const API_URL = "http://127.0.0.1:8000";

export async function getRecommendations(
  username: string,
  seller: string,
): Promise<RecommendationResponse> {
  const response = await fetch(`${API_URL}/recommend`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      username,
      seller,
    }),
  });

  if (!response.ok) {
    throw new Error(
      `Recommendation request failed: ${response.status}`,
    );
  }

  return response.json();
}