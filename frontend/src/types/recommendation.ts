export interface ScoreBreakdown {
  [key: string]: number;
}

export interface Recommendation {
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
  sleeve_condition: string;
  score: number;
  score_breakdown: ScoreBreakdown;
}

export interface RecommendationResponse {
  username: string;
  seller: string;
  sample_pages: number[];
  reported_pages: number;
  inventory_truncated: boolean;
  sampled_listings: number;
  candidates: number;
  recommendations: Recommendation[];
}
