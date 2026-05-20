export type UUID = string;
export type ISODateString = string;

export interface User {
  id: UUID;
  email: string;
  first_name?: string | null;
  last_name?: string | null;
  role?: string | null;
  workspace_id?: UUID;
  is_active?: boolean;
  created_at?: ISODateString;
}

export interface Workspace {
  id: UUID;
  name: string;
  slug?: string | null;
  created_at?: ISODateString;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export type EmailStatus = "valid" | "invalid" | "unknown" | "bounced" | "unsubscribed";

export interface Contact {
  id: UUID;
  workspace_id?: UUID;
  first_name?: string | null;
  last_name?: string | null;
  email: string;
  phone?: string | null;
  title?: string | null;
  company_id?: UUID | null;
  company_name?: string | null;
  source?: string | null;
  source_campaign?: string | null;
  source_medium?: string | null;
  first_seen_at?: ISODateString | null;
  email_status?: EmailStatus | null;
  lead_score: number;
  created_at?: ISODateString;
  updated_at?: ISODateString;
}

export interface Company {
  id: UUID;
  name: string;
  domain?: string | null;
  industry?: string | null;
  created_at?: ISODateString;
}

export interface PipelineStage {
  id: UUID;
  name: string;
  position: number;
  color?: string | null;
  is_won?: boolean;
  is_lost?: boolean;
  workspace_id?: UUID;
  created_at?: ISODateString;
}

export type CloseReason = "won" | "lost";

export interface Deal {
  id: UUID;
  name: string;
  pipeline_stage_id: UUID;
  value_cents: number;
  currency: string;
  is_active: boolean;
  lead_score?: number | null;
  contact_id?: UUID | null;
  contact_name?: string | null;
  company_id?: UUID | null;
  company_name?: string | null;
  owner_id?: UUID | null;
  owner_name?: string | null;
  stage_entered_at?: ISODateString | null;
  expected_close_date?: ISODateString | null;
  close_reason?: CloseReason | null;
  created_at?: ISODateString;
  updated_at: ISODateString;
}

export type ActivityType =
  | "email"
  | "call"
  | "sms"
  | "form_submission"
  | "note"
  | "meeting"
  | "task";

export type ActorType = "user" | "system" | "contact";

export interface ActivityItem {
  id?: UUID;
  type?: ActivityType | string | null;
  subject?: string | null;
  description?: string | null;
  occurred_at?: ISODateString | null;
  user_id?: UUID | null;
  user_name?: string | null;
  actor_type?: ActorType | null;
  actor_id?: UUID | null;
  is_ai_generated?: boolean | null;
  contact_id?: UUID | null;
  deal_id?: UUID | null;
  lead_id?: UUID | null;
}

export type Activity = ActivityItem;

export type ThreadStatus = "open" | "snoozed" | "resolved";

export interface Thread {
  id: UUID;
  status: ThreadStatus;
  subject?: string | null;
  contact_id?: UUID | null;
  contact_name?: string | null;
  assignee_id?: UUID | null;
  assignee_name?: string | null;
  message_count: number;
  last_message_at?: ISODateString | null;
  first_responded_at?: ISODateString | null;
  sla_first_response_due_at?: ISODateString | null;
  has_ai_draft?: boolean;
  created_at?: ISODateString;
  updated_at?: ISODateString;
}

export type MessageDirection = "inbound" | "outbound";

export interface Message {
  id: UUID;
  thread_id: UUID;
  body: string;
  direction: MessageDirection;
  sender?: string | null;
  created_at: ISODateString;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export type DashboardData = Record<string, unknown> & {
  activity_feed?: ActivityItem[];
  recent_activities?: ActivityItem[];
  activities?: ActivityItem[];
  open_deals_count?: number;
  my_open_deals_count?: number;
  open_deals_value_cents?: number;
  my_open_deals_value_cents?: number;
  calls_today?: number;
  emails_unread?: number;
  inbox_unread?: number;
  lead_score_alerts?: number;
};

export type DashboardStats = DashboardData;

export interface Lead {
  id: UUID;
  first_name?: string | null;
  last_name?: string | null;
  email?: string | null;
  company_name?: string | null;
  source?: string | null;
  status?: "new" | "qualified" | "converted" | "lost";
  score?: number | null;
  created_at?: ISODateString;
}
