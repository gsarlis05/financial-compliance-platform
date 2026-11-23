// VAT periods and VAT period reports (V1-2): periods chosen per company, a report per period from
// the posted ledger; Draft -> Reviewed -> Finalised -> Filed with adjustments (V1-2d); filing
// recorded by hand (nothing is sent), versions, differences, settlement.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiUrl } from "./client";
import { useScope } from "./hooks";

export type VatStatus =
  | "DRAFT"
  | "REVIEWED"
  | "FINALISED"
  | "FILED"
  | "SUPERSEDED";

export interface VatScheme {
  id: string;
  months: number;
  effective_from: string;
  note: string;
  created_at: string;
}

export interface VatReport {
  id: string;
  period_start: string;
  period_end: string;
  version: number;
  supersedes_id: string | null;
  status: VatStatus;
  snapshot_hash: string;
  watermark: number;
  generated_at: string;
  created_by_id: string;
  created_at: string;
  due_date: string | null;
  reviewed_by_id: string | null;
  reviewed_at: string | null;
  review_note: string;
  finalised_by_id: string | null;
  finalised_at: string | null;
  self_approved: boolean;
  filed_on: string | null;
  filing_reference: string;
  filing_evidence: string;
  settlement_entry_id: string | null;
}

export interface VatCodeRow {
  code: string;
  treatment: string;
  rate: string | null;
  verified: boolean;
  sales_base: string;
  sales_vat: string;
  sales_expected_vat: string;
  purchase_base: string;
  purchase_vat: string;
  purchase_expected_vat: string;
}

export interface VatLine {
  line_id: string;
  entry_id: string;
  entry_ref: string;
  date: string;
  description: string;
  account: string;
  code: string;
  kind: "SALE" | "SALE_VAT" | "PURCHASE" | "PURCHASE_VAT" | "SETTLEMENT";
  amount: string;
  counterparty: string;
  reference: string;
  // V1-2c (absent on reports prepared before the return's boxes were added)
  boxes?: Record<string, string>;
  mapping?: "MAPPED" | "EXCLUDED" | "UNSUPPORTED";
  rule?: string;
  country?: string;
  vat_no?: string;
  tax_point?: string | null;
  recovery_percent?: string | null;
  blocked?: string | null;
}

export interface VatBox {
  box: string;
  label: string;
  kind: "VAT" | "VALUE";
  amount: string;
  exact: string;
  rounding: string;
}

export interface VatReturn {
  rules: string;
  status: string;
  sources: { key: string; title: string; url?: string }[];
  boxes: VatBox[];
  checks: { check: string; ok: boolean; detail: string }[];
  direction: "PAYABLE" | "REFUNDABLE" | "NIL";
}

export interface VatSnapshot {
  return?: VatReturn;
  codes: VatCodeRow[];
  totals: {
    sales_base: string;
    sales_vat: string;
    purchase_base: string;
    purchase_vat: string;
    net: string;
    direction: "PAYABLE" | "REFUNDABLE" | "NIL";
  };
  accounts: {
    code: string;
    name: string;
    role: string;
    vat: string;
    settled: string;
  }[];
  settlements: string;
  unverified_codes: string[];
  exceptions: { kind: string; entry: string; detail: string }[];
  lines: VatLine[];
}

export interface VatAdjustment {
  id: string;
  box: string;
  amount: string;
  reason: string;
  evidence: string;
  status: "PROPOSED" | "APPROVED" | "REJECTED";
  created_by_id: string;
  created_at: string;
  decided_by_id: string | null;
  decided_at: string | null;
  decision_note: string;
  self_approved: boolean;
}

export interface VatFinalBox extends VatBox {
  original: string;
  adjustment: string;
}

export interface VatDifferences {
  changed: boolean;
  added: VatLine[];
  removed: VatLine[];
  boxes: Record<string, string>;
}

export interface VatScheduleRow {
  entry_id: string;
  entry_ref: string;
  date: string;
  description: string;
  code: string;
  category: string;
  counterparty: string;
  country: string;
  vat_no: string;
  reference: string;
  type?: string;
  net?: string;
  net_sale?: string;
  output_vat?: string;
  net_purchase?: string;
  input_vat?: string;
  blocked?: string;
  boxes: Record<string, string>;
  lines: string[];
}

export interface VatSchedule {
  rows: VatScheduleRow[];
  totals: Record<string, string>;
}

export type VatScheduleName =
  | "sales"
  | "purchases"
  | "eu_trade"
  | "reverse_charge"
  | "imports";

export interface VatReconciliation {
  accounts: {
    code: string;
    name: string;
    role: string;
    opening: string;
    vat: string;
    settled: string;
    closing: string;
    unexplained: string;
  }[];
  bridges: {
    side: "OUTPUT" | "INPUT";
    boxes: string;
    ledger: string;
    items: { item: "NOT_IN_A_BOX" | "ADJUSTMENTS"; amount: string }[];
    return: string;
    unexplained: string;
  }[];
  settlements: string;
  box_5: string;
  balanced: boolean;
}

export interface VatReportDetail extends VatReport {
  schedules: Record<VatScheduleName, VatSchedule> & {
    exceptions: { kind: string; entry: string; detail: string }[];
  };
  reconciliation: VatReconciliation | null;
  snapshot: VatSnapshot;
  final_return:
    | (Omit<VatReturn, "boxes"> & { boxes: VatFinalBox[]; adjusted: boolean })
    | null;
  adjustments: VatAdjustment[];
  blockers: string[];
  differences: VatDifferences | null;
  previous: {
    id: string;
    version: number;
    status: VatStatus;
    filed_on: string | null;
    filing_reference: string;
    boxes: Record<string, string>;
  } | null;
}

export interface VatPeriod {
  start: string;
  end: string;
  months: number;
  ended: boolean;
  report: VatReport | null;
}

export function useVatSchemes() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["vat-schemes", entityId],
    queryFn: () => api<VatScheme[]>(`${base}/vat-period-schemes`),
  });
}

export function useVatPeriods() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["vat-periods", entityId],
    queryFn: () => api<VatPeriod[]>(`${base}/vat-periods`),
  });
}

export function useVatReport(id: string | null) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["vat-report", entityId, id],
    queryFn: () => api<VatReportDetail>(`${base}/vat-reports/${id}`),
    enabled: !!id,
  });
}

export function vatExportUrl(
  base: string,
  id: string,
  format: "xlsx" | "pdf" | "csv",
  lang: string,
): string {
  return apiUrl(`${base}/vat-reports/${id}/export`, { format, lang });
}

export function useVatMutations(id: string | null) {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["vat-periods", entityId] });
    void client.invalidateQueries({ queryKey: ["vat-schemes", entityId] });
    void client.invalidateQueries({ queryKey: ["vat-report", entityId] });
  };
  const url = `${base}/vat-reports/${id}`;
  const post = <T>(path: string, body: unknown = {}) =>
    api<T>(`${url}/${path}`, { method: "POST", body });
  return {
    addScheme: useMutation({
      mutationFn: (body: {
        months: number;
        effective_from: string;
        note: string;
      }) =>
        api<VatScheme>(`${base}/vat-period-schemes`, { method: "POST", body }),
      onSuccess: refresh,
    }),
    generate: useMutation({
      mutationFn: (periodStart: string) =>
        api<VatReportDetail>(`${base}/vat-reports`, {
          method: "POST",
          body: { period_start: periodStart },
        }),
      onSuccess: refresh,
    }),
    act: useMutation({
      mutationFn: (
        what: "regenerate" | "review" | "finalise" | "new-version",
      ) => post<VatReportDetail>(what),
      onSuccess: refresh,
    }),
    dueDate: useMutation({
      mutationFn: (due: string | null) =>
        api<VatReportDetail>(`${url}/due-date`, {
          method: "PUT",
          body: { due_date: due },
        }),
      onSuccess: refresh,
    }),
    filed: useMutation({
      mutationFn: (body: {
        filed_on: string;
        reference: string;
        evidence: string;
      }) => post<VatReportDetail>("filed", body),
      onSuccess: refresh,
    }),
    reopen: useMutation({
      mutationFn: (note: string) => post<VatReportDetail>("reopen", { note }),
      onSuccess: refresh,
    }),
    propose: useMutation({
      mutationFn: (body: {
        box: string;
        amount: string;
        reason: string;
        evidence: string;
      }) => post<VatAdjustment>("adjustments", body),
      onSuccess: refresh,
    }),
    decide: useMutation({
      mutationFn: ({ id: adj, approve }: { id: string; approve: boolean }) =>
        post<VatAdjustment>(
          `adjustments/${adj}/${approve ? "approve" : "reject"}`,
          { note: "" },
        ),
      onSuccess: refresh,
    }),
    settlement: useMutation({
      mutationFn: () => post<{ entry_id: string }>("settlement"),
      onSuccess: refresh,
    }),
  };
}
