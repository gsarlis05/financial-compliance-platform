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
  control_type: "" | "RECEIVABLE" | "PAYABLE";
  vat_role: "" | "INPUT" | "OUTPUT";
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

export type EntryStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "APPROVED"
  | "POSTED"
  | "REJECTED"
  | "VOID";

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
  counterparty_id: string | null;
  counterparty_code: string | null;
  reference: string;
  due_date: string | null;
  vat_code_id: string | null;
  vat_code: string | null;
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
    counterparty_id?: string | null;
    reference?: string;
    vat_code_id?: string | null;
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

export type CounterpartyKind =
  | "CUSTOMER"
  | "SUPPLIER"
  | "BOTH"
  | "EMPLOYEE"
  | "TAX_AUTHORITY"
  | "LENDER";

export interface Counterparty {
  id: string;
  code: string;
  name: string;
  kind: CounterpartyKind;
  vat_no: string;
  email: string;
  payment_terms_days: number;
  status: "ACTIVE" | "INACTIVE";
}

export type Side = "RECEIVABLE" | "PAYABLE";

export interface OpenItem {
  line_id: string;
  entry_id: string;
  entry_ref: string;
  side: Side;
  kind: "INVOICE" | "PAYMENT";
  account_code: string;
  counterparty_id: string;
  counterparty_code: string;
  accounting_date: string;
  due_date: string;
  days_overdue: number;
  reference: string;
  description: string;
  amount: Amount;
  allocated: Amount;
  open_amount: Amount;
  status: "OPEN" | "PARTIAL" | "SETTLED";
  disputed: boolean;
  note: string;
}

export const BUCKETS = [
  "current",
  "1_30",
  "31_60",
  "61_90",
  "over_90",
] as const;
export type Bucket = (typeof BUCKETS)[number];

export interface AgeingRow {
  counterparty_id: string;
  counterparty_code: string;
  counterparty_name: string;
  buckets: Record<Bucket, Amount>;
  unapplied: Amount;
  total: Amount;
}

export interface Ageing {
  as_of: string;
  side: Side;
  rows: AgeingRow[];
  totals: Record<Bucket, Amount>;
  unapplied: Amount;
  total: Amount;
  control_balance: Amount;
  reconciles: boolean;
}

export interface VatCode {
  id: string;
  code: string;
  name: string;
  name_el: string;
  treatment: string;
  rate: string | null;
  valid_from: string | null;
  valid_to: string | null;
  verified: boolean;
  verification_note: string;
}

export interface TaxonomyLine {
  code: string;
  name: string;
  name_el: string;
  statement: "BS" | "PL";
  section: string;
  account_types: string[];
  direction: string;
  order: number;
}

export interface MappingRow {
  account_id: string;
  account_code: string;
  account_name: string;
  account_type: string;
  line_code: string | null;
  balance: Amount;
  has_activity: boolean;
}

export interface MappingCompleteness {
  as_of: string;
  taxonomy: string;
  complete: boolean;
  mapped: number;
  unmapped_blocking: MappingRow[];
  unmapped_warning: MappingRow[];
  unmapped_idle: number;
}

export interface StatementAccount {
  account_id: string | null;
  code: string;
  name: string;
  name_el: string;
  current: Amount;
  comparative: Amount | null;
}

export interface StatementRow {
  kind: "heading" | "line" | "subtotal" | "total";
  code: string;
  name: string;
  name_el: string;
  current: Amount | null;
  comparative: Amount | null;
  accounts: StatementAccount[];
}

export interface StatementCheck {
  code: string;
  column: "current" | "comparative";
  ok: boolean;
  values: Record<string, Amount>;
}

export interface Statement {
  kind: "PL" | "BS" | "CF";
  name: string;
  name_el: string;
  rows: StatementRow[];
  checks: StatementCheck[];
}

export interface Statements {
  entity_name: string;
  taxonomy: string;
  watermark: number;
  date_from: string;
  date_to: string;
  comparative_from: string | null;
  comparative_to: string | null;
  ok: boolean;
  profit_and_loss: Statement;
  balance_sheet: Statement;
  cash_flow: Statement;
}

export interface AccountLedgerLine {
  entry_id: string;
  entry_ref: string;
  accounting_date: string;
  description: string;
  memo: string;
  debit: Amount;
  credit: Amount;
  running_balance: Amount;
  restated_after_lock: boolean;
}

export interface AccountLedger {
  account_id: string;
  code: string;
  name: string;
  date_from: string;
  date_to: string;
  opening_balance: Amount;
  lines: AccountLedgerLine[];
  closing_balance: Amount;
}

export interface CloseStatus {
  fiscal_year_id: string;
  name: string;
  status: "OPEN" | "CLOSED";
  end_date: string;
  result: Amount;
  lines: {
    account_id: string;
    account_code: string;
    account_name: string;
    account_type: string;
    dimension_value_ids: string[];
    balance: Amount;
  }[];
  blockers: string[];
  closing_entry_id: string | null;
  closing_entry_status: EntryStatus | null;
  reopen_entry_id: string | null;
  checks: { code: string; ok: boolean; details: string[] }[];
}

export interface Reconciliation {
  as_of: string;
  statement_balance: Amount;
  ledger_balance: Amount;
  difference: Amount;
  unmatched_lines: number;
  reconciled: boolean;
}

export interface BankAccount {
  id: string;
  name: string;
  iban: string;
  currency: string;
  ledger_account_id: string;
  status: string;
  csv_mapping: Record<string, unknown> | null;
  last_reconciled: Reconciliation | null;
  unmatched_lines: number;
}

export interface StatementImport {
  id: string;
  format: "CAMT053" | "CSV";
  filename: string;
  status: "PENDING" | "DONE" | "FAILED";
  error: string;
  statement_id: string;
  opening_balance: Amount | null;
  closing_balance: Amount | null;
  closing_date: string | null;
  lines_created: number;
  lines_duplicate: number;
  created_at: string;
  processed_at: string | null;
}

export interface StatementLine {
  id: string;
  booking_date: string;
  value_date: string | null;
  amount: Amount;
  description: string;
  counterparty_name: string;
  reference: string;
  bank_ref: string;
  status: "UNMATCHED" | "MATCHED" | "IGNORED";
  matched_line_id: string | null;
  note: string;
}

export interface MatchCandidate {
  journal_line_id: string;
  entry_id: string;
  entry_ref: string;
  accounting_date: string;
  amount: Amount;
  reference: string;
  description: string;
}

export interface PaymentSuggestion {
  counterparty_id: string;
  counterparty_code: string;
  account_code: string;
  reference: string;
  due_date: string;
  open_amount: Amount;
  reference_matches: boolean;
}

export interface DocumentInfo {
  id: string;
  filename: string;
  content_type: string;
  size: number;
  sha256: string;
  created_at: string;
  uploaded_by_id: string;
  links: { id: string; entry_id: string | null; line_id: string | null }[];
}

// --- commitments: recurring obligations, loans, facilities, holidays (M3-4) ----------------------

export type Adjustment =
  | "NONE"
  | "FOLLOWING"
  | "MODIFIED_FOLLOWING"
  | "PRECEDING";
export type Frequency = "WEEKLY" | "MONTHLY" | "QUARTERLY" | "YEARLY";
export type ObligationCategory =
  | "RENT"
  | "PAYROLL"
  | "SOCIAL_INSURANCE"
  | "SUBSCRIPTION"
  | "LEASE"
  | "INSURANCE"
  | "UTILITIES"
  | "INCOME"
  | "OTHER";
export type CommitmentNature = "COMMITTED" | "EXPECTED";

export interface ObligationInput {
  name: string;
  category: ObligationCategory;
  direction: "OUTFLOW" | "INFLOW";
  amount: string;
  frequency: Frequency;
  interval: number;
  day_of_month: number | null;
  start_date: string;
  end_date: string | null;
  adjust: Adjustment;
  contractual: boolean;
  counterparty_id: string | null;
  note: string;
}

export interface Obligation extends ObligationInput {
  id: string;
  series_id: string;
  version: number;
  currency: string;
  nature: CommitmentNature;
  superseded_at: string | null;
  created_at: string;
}

export type DebtKind =
  | "TERM_LOAN"
  | "LEASE"
  | "DIRECTOR_LOAN"
  | "OVERDRAFT"
  | "REVOLVER";
export type Repayment =
  | ""
  | "ANNUITY"
  | "LINEAR"
  | "BULLET"
  | "IO_THEN_ANNUITY";

export interface DebtInput {
  name: string;
  kind: DebtKind;
  principal: string | null;
  facility_limit: string | null;
  start_date: string;
  maturity_date: string | null;
  payment_frequency_months: 1 | 3 | 6 | 12;
  rate_type: "FIXED" | "VARIABLE";
  fixed_rate: string | null;
  reference_rate_key: string;
  margin: string | null;
  assumed_reference_rate: string | null;
  day_count: "ACT_360" | "ACT_365" | "30_360";
  repayment_type: Repayment;
  interest_only_periods: number;
  adjust: Adjustment;
  lender_id: string | null;
  note: string;
}

export interface Debt extends DebtInput {
  id: string;
  series_id: string;
  version: number;
  superseded_at: string | null;
  created_at: string;
}

export interface Instalment {
  number: number;
  period_start: string;
  period_end: string;
  due: string;
  opening: string;
  interest: string;
  principal: string;
  payment: string;
  closing: string;
}

export interface Holiday {
  id: string;
  day: string;
  name: string;
}

export interface CommitmentFlow {
  due: string;
  scheduled: string;
  amount: string;
  nature: CommitmentNature;
  source: "OBLIGATION" | "DEBT" | "TAX";
  component: "PAYMENT" | "PRINCIPAL" | "INTEREST";
  category: string;
  name: string;
  series_id: string;
  version_id: string;
}

// --- tax payment calendar (M3-5) ------------------------------------------------------------------

export type TaxKind =
  | "VAT"
  | "CORPORATE_TAX"
  | "SPECIAL_DEFENCE"
  | "SOCIAL_INSURANCE"
  | "PAYE"
  | "OTHER";

export interface TaxPaymentInput {
  kind: TaxKind;
  period_label: string;
  due_date: string;
  amount: string;
  nature: CommitmentNature;
  reference: string;
  paid_on: string | null;
  note: string;
}

export interface TaxPayment extends TaxPaymentInput {
  id: string;
  series_id: string;
  version: number;
  superseded_at: string | null;
  created_at: string;
}
