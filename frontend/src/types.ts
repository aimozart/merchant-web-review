export interface RiskSignal {
  id: string;
  category: "domain" | "content" | "social" | "reputation";
  severity: "info" | "low" | "medium" | "high";
  label: string;
  detail: string;
}

export interface WebPresenceReview {
  id: string;
  status: "queued" | "scraping" | "analyzing" | "complete" | "failed";
  is_monitoring_check: boolean;
  recommendation: "" | "pass" | "fail" | "review";
  summary: string;
  error_message: string;
  created_at: string;
  completed_at: string | null;
  signals: RiskSignal[];
}

export interface Merchant {
  id: string;
  business_name: string;
  website_url: string;
  created_at: string;
  monitoring_enabled: boolean;
  monitoring_interval_hours: number;
  latest_review: WebPresenceReview | null;
}

export type TicketStatus = "open" | "in_progress" | "resolved" | "closed";
export type TicketPriority = "low" | "medium" | "high" | "critical";
export type TicketCategory = "infra" | "data" | "integration" | "performance";
export type TicketSource = "health_check" | "fault_injection" | "manual";

export interface Ticket {
  id: string;
  title: string;
  description: string;
  status: TicketStatus;
  priority: TicketPriority;
  category: TicketCategory;
  source: TicketSource;
  related_merchant: string | null;
  related_review: string | null;
  resolution_notes: string;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
