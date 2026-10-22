// Shapes mirror backend/app/api/routes.py. Nullable where the ORM column is nullable.

export type AdStatus =
  | "DETECTED_ACTIVE_SIGNALS"
  | "POSSIBLE"
  | "DECLARED_AUTHORIZATION_ONLY"
  | "NOT_OBSERVED"
  | "SCAN_INCONCLUSIVE";

export interface WebsiteRow {
  id: number;
  host: string;
  registrable_domain: string | null;
  primary_category: string | null;
  is_publisher: boolean | null;
  classification_confidence: number | null;
  primary_geo: string | null;
  country_signals: unknown;
  language: string | null;
  crux_best_bucket: number | null;
  tranco_best_rank: number | null;
  monetization_type: string | null;
  gam_status: AdStatus | null;
  adsense_status: AdStatus | null;
  prebid_status: AdStatus | null;
  observed_partners: string[] | null;
  declared_ad_systems_count: number | null;
  opportunity_types: string[] | null;
  score_total: number | null;
  queue: string | null;
  evidence_confidence: number | null;
  contact_status: string | null;
  last_analyzed_at: string | null;
  outreach_stage: string | null;
  excluded: boolean | null;
  exclusion_reason: string | null;
  first_discovered_at: string | null;
  discovery_priority: number | null;
}

export interface VendorCondition { vendor: string; statuses?: string[] }

export interface WebsiteFilter {
  q?: string | null;
  ids?: number[] | null;
  categories?: string[] | null;
  is_publisher?: boolean | null;
  queues?: string[] | null;
  opportunity_types?: string[] | null;
  max_crux_bucket?: number | null;
  max_tranco_rank?: number | null;
  geos?: string[] | null;
  monetization_types?: string[] | null;
  gam?: string[] | null;
  adsense?: string[] | null;
  prebid?: string[] | null;
  has_vendors?: VendorCondition[] | null;
  lacks_vendors?: string[] | null;
  ads_txt_systems?: string[] | null;
  seller_account_id?: string | null;
  min_score?: number | null;
  excluded?: boolean | null;
  sources?: string[] | null;
  outreach_stages?: string[] | null;
  analyzed?: boolean | null;
  sort?: string[];
}

export interface SearchResult { total: number; page: number; page_size: number; rows: WebsiteRow[]; columns: string[] }

export interface Job {
  id: number;
  kind: string;
  status: string;
  params?: Record<string, unknown> | null;
  progress: Record<string, unknown> | null;
  error?: string;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  heartbeat_at?: string | null;
}

export interface Dashboard {
  totals: Record<string, number>;
  queues: Record<string, number>;
  categories: Record<string, number>;
  opportunities: Record<string, number>;
  monetization: Record<string, number>;
  crux_buckets: Record<string, number>;
  sources: Record<string, number>;
  stages: Record<string, Record<string, number>>;
  jobs: Job[];
  new_promising: WebsiteRow[];
  top_prospects: WebsiteRow[];
  recent_failures: { stage: string; host: string; error: string | null; updated_at: string }[];
  traffic_note: string;
}

export interface Vendor { key: string; name: string; category: string; ads_txt: unknown; bidders: unknown }
export interface VendorsResp { version: string; vendors: Vendor[] }

export interface SavedView { id: number; name: string; filters: WebsiteFilter; columns: string[] | null }

export interface Evidence { kind: string; value: string | null; page_url: string | null; observation: string | null; scan_id: number | null }

export interface Technology {
  id: number;
  vendor_key: string;
  vendor_name: string;
  category: string;
  status: AdStatus;
  confidence: number | null;
  detail: Record<string, unknown> | null;
  evidence: Evidence[];
  engine: string | null;
  created_at: string;
}

export interface ClassificationEntry {
  id: number;
  primary_category: string | null;
  secondary: string[] | null;
  is_publisher: boolean | null;
  confidence: number | null;
  supporting: Record<string, unknown>[] | null;
  contradictory: Record<string, unknown>[] | null;
  pages_inspected: string[] | null;
  features: Record<string, unknown> | null;
  method: string | null;
  engine: string | null;
  is_current: boolean;
  created_at: string;
}

export interface AdsTxtFileT {
  id: number; url: string | null; final_url: string | null; http_status: number | null; status: string | null;
  record_count: number | null; malformed_count: number | null; variables: Record<string, unknown> | null;
  malformed_sample: unknown; fetched_at: string; is_current: boolean;
}

export interface AdsTxtRecordT {
  ad_system_domain: string; seller_account_id: string; relationship: string | null; cert_authority_id: string | null;
  vendor_key: string | null; line_no: number | null;
  seller: { name: string | null; domain: string | null; seller_type: string | null; is_confidential: boolean | null; domain_matches_site: boolean } | null;
}

export interface OpportunityT {
  type: string; label: string; confidence: number | null; evidence: Record<string, unknown>[] | null; hypothesis: string | null;
  missing: string[] | null; verification: string | null; approach: string | null; engine: string | null; created_at: string;
}

export interface ScoreT {
  popularity: number | null; ad_opportunity: number | null; audience_geo: number | null; inventory: number | null;
  actionability: number | null; evidence_quality: number | null; total: number | null; queue: string | null;
  computed_queue: string | null; evidence_confidence: number | null; explanation: Record<string, string[]> | null;
  missing_critical: string[] | null; next_action: string | null; max: Record<string, number> | null; engine: string | null; created_at: string;
}

export interface ScanPageT {
  id: number; url: string; final_url: string | null; role: string | null; http_status: number | null;
  blocked_reason: string | null; html_sha256: string | null; network_request_count: number;
}
export interface ScanT { id: number; kind: string; method: string | null; status: string; error: string | null; started_at: string; pages: ScanPageT[] }

export interface StageT { stage: string; status: string; attempts: number; last_error: string | null; detail: unknown; updated_at: string }

export interface Profile {
  website: WebsiteRow & { preferred_origin: string | null; canonical_host: string | null; redirects_to_website_id: number | null };
  organization: { name: string; source: string | null } | null;
  sources: { type: string; ref: string | null; original: string | null; payload: unknown; first_seen: string; last_seen: string }[];
  stages: StageT[];
  classification: ClassificationEntry[];
  popularity: { source: string; period: string | null; country: string | null; rank_bucket: number | null; rank: number | null; origin: string | null; source_url: string | null; retrieved_at: string }[];
  technologies: Technology[];
  inventory: Record<string, unknown> | null;
  ads_txt: { files: AdsTxtFileT[]; records: AdsTxtRecordT[] };
  opportunities: OpportunityT[];
  score: ScoreT | null;
  score_history: { at: string; total: number | null; queue: string | null }[];
  scans: ScanT[];
  overrides: { field: string; value: string; reason: string; user_id: number | null; active: boolean; created_at: string }[];
  outreach: { stage: string; notes: string | null; owner_id: number | null; imported_status: string | null } | null;
  contacts: { email: string | null; name: string | null; role: string | null; source_url: string | null; verification_status: string | null }[];
  business_links: unknown;
}

export interface SupplyGraph {
  nodes: { id: string; label: string; type: "site" | "ad_system"; vendor_key?: string | null; observed_status?: AdStatus | null }[];
  edges: { from: string; to: string; relationship: string | null; accounts: number }[];
}

export interface RelatedResp {
  host: string;
  groups: { ad_system_domain: string; seller_account_id: string; seller_name: string | null; seller_type: string | null; seller_domain: string | null; websites: { id: number; host: string }[]; hypothesis: string }[];
}

export interface NetworkResp { url: string; network_requests: Record<string, unknown>[]; script_urls: string[]; page_globals: unknown }

export interface UploadPreview { token: string; filename: string; size: number; columns: string[]; rows: Record<string, unknown>[]; suggested_mapping: Record<string, string> }

export interface BoardResp { stages: string[]; board: Record<string, WebsiteRow[]> }

export interface SettingsResp { settings: Record<string, unknown>; environment: Record<string, unknown> }
export interface UserT { id: number; email: string; role: string; is_active: boolean }
export interface ExclusionT { id: number; kind: string; pattern: string; reason: string; created_at: string }
export interface AuditT { at: string; user_id: number | null; action: string; entity: string; entity_id: string | null; data: unknown }
