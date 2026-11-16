// Response shapes of the backend API. Monetary amounts are decimal strings, never numbers.

export type Amount = string;

export interface Me {
  id: string;
  email: string;
  display_name: string;
  locale: string;
  auth_time: number | null;
  amr: string[];
}

export type WorkspaceKind = "FIRM" | "BUSINESS" | "PERSONAL";

export interface Workspace {
  id: string;
  slug: string;
  name: string;
  kind: WorkspaceKind;
  roles: string[];
}

export interface LegalEntity {
  id: string;
  legal_name: string;
  entity_type: string;
  registration_no: string;
  jurisdiction: string;
  functional_currency: string;
  status: string;
}

export interface Account {
  id: string;
  code: string;
  name: string;
  name_el: string;
  type: "ASSET" | "LIABILITY" | "EQUITY" | "INCOME" | "EXPENSE";
  normal_side: "DEBIT" | "CREDIT";
  parent_id: string | null;
  is_postable: boolean;
  status: "ACTIVE" | "INACTIVE";
  currency: string;
}

export type PeriodStatus = "OPEN" | "SOFT_CLOSED" | "LOCKED";

export interface Period {
  id: string;
  number: number;
  start_date: string;
  end_date: string;
  is_adjustment: boolean;
  status: PeriodStatus;
}

export interface FiscalYear {
  id: string;
  name: string;
  start_date: string;
  end_date: string;
  status: string;
  periods: Period[];
}

export type EntryStatus = "DRAFT" | "SUBMITTED" | "APPROVED" | "POSTED" | "REJECTED" | "VOID";

export interface LineDimension {
  dimension_id: string;
  dimension_code: string;
  value_id: string;
  value_code: string;
  value_name: string;
}

export interface EntryLine {
  line_no: number;
  account_id: string;
  account_code: string;
  debit: Amount;
  credit: Amount;
  memo: string;
  dimensions: LineDimension[];
}

export type DimensionKind = "DEPARTMENT" | "PROJECT" | "COST_CENTRE" | "CUSTOM";

export interface DimensionValue {
  id: string;
  code: string;
  name: string;
  parent_id: string | null;
  status: "ACTIVE" | "INACTIVE";
}

export interface Dimension {
  id: string;
  code: string;
  name: string;
  kind: DimensionKind;
  status: "ACTIVE" | "INACTIVE";
  values: DimensionValue[];
}

export interface JournalEntry {
  id: string;
  status: EntryStatus;
  entry_type: string;
  journal: string;
  entry_no: number | null;
  posting_seq: number | null;
  accounting_date: string;
  document_date: string | null;
  use_adjustment_period: boolean;
  description: string;
  currency: string;
  period_id: string | null;
  reverses_entry_id: string | null;
  reversed_by_entry_id: string | null;
  related_entry_id: string | null;
  correction_reason: string;
  prepared_by_id: string;
  approved_by_id: string | null;
  posted_by_id: string | null;
  rejection_reason: string;
  unlock_request_id: string | null;
  content_hash: string;
  total_debit: Amount;
  total_credit: Amount;
  lines: EntryLine[];
}

export interface EntryInput {
  accounting_date: string;
  description: string;
  use_adjustment_period: boolean;
  lines: {
    account_id: string;
    debit: Amount;
    credit: Amount;
    memo: string;
    dimension_value_ids: string[];
  }[];
}

export interface TrialBalanceRow {
  account_id: string;
  code: string;
  name: string;
  type: string;
  debit: Amount;
  credit: Amount;
  balance: Amount;
}

export interface TrialBalance {
  as_of: string;
  date_from: string | null;
  rows: TrialBalanceRow[];
  total_debit: Amount;
  total_credit: Amount;
  unposted_entries: number;
  restated_after_lock: number;
}

export interface PeriodUnlock {
  id: string;
  period_id: string;
  reason: string;
  window_minutes: number;
  status: "REQUESTED" | "ACTIVE" | "REJECTED" | "CLOSED";
  requested_by_id: string;
  first_approver_id: string | null;
  second_approver_id: string | null;
  active_until: string | null;
}

export interface IntegrityRun {
  id: string;
  status: "PASSED" | "FAILED";
  trigger: string;
  created_at: string;
  results: { check: string; ok: boolean; details: string[] }[];
}
