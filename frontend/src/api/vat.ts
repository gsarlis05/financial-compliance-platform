// VAT periods and VAT period reports (V1-2): periods chosen per company, a report per period from
// the posted ledger, sign-off, filing recorded by hand (nothing is sent), versions, settlement.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiUrl } from "./client";
import { useScope } from "./hooks";

export type VatStatus = "DRAFT" | "SIGNED_OFF" | "FILED" | "SUPERSEDED";

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
  due_date: string | null;
  signed_off_by_id: string | null;
  signed_off_at: string | null;
  self_approved: boolean;
  filed_on: string | null;
  filing_reference: string;
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

export interface VatReportDetail extends VatReport {
  snapshot: VatSnapshot;
  blockers: string[];
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
  format: "xlsx" | "pdf",
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
      mutationFn: (what: "regenerate" | "sign-off" | "new-version") =>
        post<VatReportDetail>(what),
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
      mutationFn: (body: { filed_on: string; reference: string }) =>
        post<VatReportDetail>("filed", body),
      onSuccess: refresh,
    }),
    settlement: useMutation({
      mutationFn: () => post<{ entry_id: string }>("settlement"),
      onSuccess: refresh,
    }),
  };
}
