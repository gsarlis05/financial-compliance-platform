// Budgets (M4-1): response shapes and hooks.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { useScope } from "./hooks";

export type BudgetKind = "ANNUAL" | "DEPARTMENTAL" | "PROJECT";
export type VersionStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "APPROVED"
  | "LOCKED"
  | "SUPERSEDED";

export interface BudgetVersion {
  id: string;
  number: number;
  status: VersionStatus;
  reason: string;
  supersedes_id: string | null;
  content_hash: string;
  created_by_id: string;
  submitted_by_id: string | null;
  submitted_at: string | null;
  approved_by_id: string | null;
  approved_at: string | null;
  sod_applied: boolean | null;
  locked_at: string | null;
  superseded_at: string | null;
}

export interface Budget {
  id: string;
  name: string;
  kind: BudgetKind;
  fiscal_year_id: string;
  fiscal_year_start: string;
  fiscal_year_end: string;
  dimension_value_id: string | null;
  original_version_id: string | null;
  current_version_id: string | null;
  open_version_id: string | null;
  versions: BudgetVersion[];
}

export interface BudgetLine {
  id: string;
  seq: number;
  taxonomy_code: string | null;
  taxonomy_name: string | null;
  direction: string | null;
  account_id: string | null;
  dimension_value_id: string | null;
  method: string;
  note: string;
  nature: "BUDGET";
  amounts: string[];
  quarters: string[];
  total: string;
}

export interface BudgetVersionDetail extends BudgetVersion {
  budget_id: string;
  months: string[];
  lines: BudgetLine[];
  month_totals: string[];
  total: string;
}

export interface BudgetEvent {
  version_number: number;
  seq: number;
  action: string;
  actor_id: string;
  actor_name: string;
  comment: string;
  at: string;
}

export interface LineIn {
  taxonomy_code: string | null;
  account_id: string | null;
  dimension_value_id: string | null;
  amounts: Record<string, string>;
  note: string;
}

export function useBudgets(fiscalYearId: string) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["budgets", entityId, fiscalYearId],
    queryFn: () =>
      api<Budget[]>(
        `${base}/budgets${fiscalYearId ? `?fiscal_year_id=${fiscalYearId}` : ""}`,
      ),
  });
}

export function useBudgetVersion(versionId: string | null) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["budget-version", entityId, versionId],
    queryFn: () =>
      api<BudgetVersionDetail>(`${base}/budget-versions/${versionId}`),
    enabled: !!versionId,
  });
}

export function useBudgetEvents(budgetId: string | null) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["budgets", entityId, "events", budgetId],
    queryFn: () => api<BudgetEvent[]>(`${base}/budgets/${budgetId}/events`),
    enabled: !!budgetId,
  });
}

export function useBudgetSettings() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["budget-settings", entityId],
    queryFn: () => api<{ sod_required: boolean }>(`${base}/budget-settings`),
  });
}

export function useBudgetMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: ["budgets", entityId] });
    await client.invalidateQueries({ queryKey: ["budget-version", entityId] });
  };
  const useAction = (name: string) =>
    useMutation({
      mutationFn: ({ versionId, body }: { versionId: string; body?: object }) =>
        api<BudgetVersion | BudgetVersionDetail>(
          `${base}/budget-versions/${versionId}/${name}`,
          { method: "POST", body: body ?? {} },
        ),
      onSuccess: refresh,
    });
  return {
    create: useMutation({
      mutationFn: (body: {
        name: string;
        fiscal_year_id: string;
        kind: BudgetKind;
        dimension_value_id: string | null;
      }) => api<Budget>(`${base}/budgets`, { method: "POST", body }),
      onSuccess: refresh,
    }),
    saveLines: useMutation({
      mutationFn: ({
        versionId,
        lines,
      }: {
        versionId: string;
        lines: LineIn[];
      }) =>
        api<BudgetVersionDetail>(`${base}/budget-versions/${versionId}/lines`, {
          method: "PUT",
          body: { lines },
        }),
      onSuccess: refresh,
    }),
    submit: useAction("submit"),
    approve: useAction("approve"),
    returnToDraft: useAction("return"),
    lock: useAction("lock"),
    revise: useAction("revise"),
    saveSettings: useMutation({
      mutationFn: (sodRequired: boolean) =>
        api<{ sod_required: boolean }>(`${base}/budget-settings`, {
          method: "PUT",
          body: { sod_required: sodRequired },
        }),
      onSuccess: () =>
        client.invalidateQueries({ queryKey: ["budget-settings", entityId] }),
    }),
  };
}
