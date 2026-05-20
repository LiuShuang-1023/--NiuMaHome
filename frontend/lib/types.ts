// 与后端 schemas.py 对齐
export type ChatRole = 'user' | 'assistant';

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export interface GeoPoint {
  lng: number | null;
  lat: number | null;
}

export interface Destination {
  city: string;
  district: string;
  landmark: string;
  address: string;
  geo: GeoPoint;
}

export interface CommuteRequirement {
  max_minutes: number;
  modes: string[];
  maps: string[];
}

export interface RentalType {
  include: string[];
  exclude: string[];
}

export interface PriceRange {
  base_rent_max: number | null;
  base_rent_min: number | null;
  total_cost_max: number | null;
  total_cost_min: number | null;
}

export interface ParsedRequirement {
  destination: Destination;
  commute: CommuteRequirement;
  rental_type: RentalType;
  price: PriceRange;
  soft_preferences: string[];
  hard_excludes: string[];
  raw_text?: string;
}

export interface ChatResponse {
  reply: string;
  requirement: ParsedRequirement | null;
  is_ready: boolean;
  clarifying_questions: string[];
}

export interface Listing {
  id: string;
  platform: string;
  platform_id: string;
  url: string;
  title: string;
  price_base: number;
  price_total: number | null;
  area: number | null;
  layout: string | null;
  floor: string | null;
  has_elevator: boolean | null;
  orientation: string | null;
  rental_type_tag: string | null;
  address: string;
  community: string;
  geo_lng: number | null;
  geo_lat: number | null;
  images: string[];
  raw_data: Record<string, unknown>;
  confidence_score: number;
  missing_fields: string[];
}

export interface CostBreakdown {
  base_rent: number;
  property_fee: number;
  water: number;
  electricity: number;
  gas: number;
  internet: number;
  agency_fee_monthly: number;
  deposit_cost: number;
  other: number;
  total: number;
  notes: Record<string, string>;
}

export interface CommuteResult {
  map_provider: 'amap' | 'baidu' | 'tencent' | 'stable_baseline';
  mode: 'transit' | 'riding' | 'walking' | 'driving';
  duration_min: number;
  distance_km: number;
  direction: 'home_to_work' | 'work_to_home';
  nearest_metro: string | null;
  metro_walk_min: number | null;
  metro_distance_m: number | null;
  transfers: number | null;
}

export interface CommuteSummary {
  listing_id: string;
  destination_address: string;
  results: CommuteResult[];
  best_duration_min: number;
  avg_transit_min: number | null;
  nearest_metro: string | null;
  metro_walk_min: number | null;
}

export interface Recommendation {
  listing: Listing;
  cost: CostBreakdown;
  commute: CommuteSummary | null;
  score: number;
  rank: number;
  reason: string;
  flags: string[];
  ai_review?: ListingReview | null;
}

export interface ListingReview {
  score: number;
  summary: string;
  pros: string[];
  cons: string[];
  tags: string[];
  generated_at: string;
  model: string;
}

export interface ListingReviewResponse {
  review: ListingReview;
  cached: boolean;
}

export interface SearchResponse {
  session_id: string;
  recommendations: Recommendation[];
  total_crawled: number;
  total_filtered: number;
  total_pages: number;
  current_page: number;
  message: string;
  has_commute: boolean;
  sources?: Record<string, number>;
  counts_by_platform?: Record<string, number>;
  // v0.3.0
  geo_filter_stats?: {
    total: number;
    geocoded: number;
    geocode_failed: number;
    within_radius: number;
    out_of_radius: number;
    offline_estimated?: number;
  };
  commute_source_stats?: {
    offline?: number;
    amap?: number;
    baidu?: number;
    total?: number;
    precise?: number;
  };
  radius_km?: number;
  // v0.3.0.1: geocode 精度
  geocode_precision?: '' | 'exact' | 'district' | 'city';
  geocode_warning?: string;
  dest_label?: string;
  quota_status?: {
    amap?: {
      available: boolean;
      quota_exhausted: boolean;
      key_invalid: boolean;
      rate_limit_hits: number;
    };
    tencent?: {
      available: boolean;
      quota_exhausted: boolean;
      key_invalid: boolean;
    };
    baidu?: {
      available: boolean;
      quota_exhausted: boolean;
      concurrency_limit_hit: boolean;
      key_invalid: boolean;
    };
  };
}

export interface PreciseOneResponse {
  listing_id: string;
  success: boolean;
  source: string;
  duration_min: number;
  fail_reason?: string;
}

export interface PreciseBatchResponse extends SearchResponse {
  round_attempted: number;
  round_success: number;
  round_fail: number;
}

export type SortMode = '综合' | '价格' | '通勤' | '面积';
export type PlatformFilter = 'all' | 'lianjia' | 'beike' | 'anjuke' | 'wuba';
