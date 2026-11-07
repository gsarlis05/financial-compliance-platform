// KPIs (M4-4): response shapes and hooks.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./client";
import { useScope } from "./hooks";

export type KpiDisplay =
  | "percent"
  | "ratio"
  | "times"
  | "days"
  | "months"
  | "EUR";

export interface KpiValue {
  result_id: string;
  definition_id: string;
  key: string;
  name: string;
  name_el: string;
  category: string;
  display: KpiDisplay;
  direction: string;
  convention: string;
  nature: "ACTUAL";
  value: string | null;
  unit: string;
  nm_reason: string;
  non_ledger: boolean;
}

export interface KpiSet {
  run_id: string;
  status: string;
  stale: boolean;
  library: string;
  date_from: string;
  date_to: string;
  actuals_watermark: number;
  created_at: string;
  unmapped_accounts: number;
  values: KpiValue[];
}

export interface KpiDefinition {
  id: string;
  key: string;
  formula: string;
  nm_note: string;
  example: string;
}

/** The latest KPI set for the period, or null when none has been calculated (404). */
export function useLatestKpis(dateFrom: string, dateTo: string) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["kpis", entityId, dateFrom, dateTo],
    queryFn: async () => {
      try {
        return await api<KpiSet>(`${base}/kpi-sets/latest`, {
          query: { date_from: dateFrom, date_to: dateTo },
        });
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
  });
}

export function useKpiDefinitions() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["kpi-definitions", entityId],
    queryFn: () => api<KpiDefinition[]>(`${base}/kpi-definitions`),
    staleTime: 300_000,
  });
}

export function useRunKpis() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (period: { date_from: string; date_to: string }) =>
      api<KpiSet>(`${base}/kpi-sets`, { method: "POST", body: period }),
    onSuccess: (made) =>
      client.setQueryData(
        ["kpis", entityId, made.date_from, made.date_to],
        made,
      ),
  });
}

// --- custom KPIs and operational metrics (M4-5) -------------------------------------------------

export interface CustomKpi {
  id: string;
  key: string;
  version: number;
  scope: "PERSONAL" | "WORKSPACE";
  status:
    | "ACTIVE"
    | "SUBMITTED"
    | "APPROVED"
    | "REJECTED"
    | "SUPERSEDED"
    | "RETIRED";
  name: string;
  formula: string;
  unit: string;
  display: KpiDisplay;
  direction: "HIGHER_BETTER" | "LOWER_BETTER";
  convention: string;
  owner_name: string;
  supersedes_id: string | null;
  decided_by_name: string;
  decided_at: string | null;
  decision_comment: string;
  created_at: string;
}

export interface CustomKpiIn {
  key: string;
  name: string;
  formula: string;
  display: KpiDisplay;
  direction: "HIGHER_BETTER" | "LOWER_BETTER";
  convention: string;
}

export interface FormulaCheck {
  ok: boolean;
  unit: string | null;
  problems: string[];
  dry_run_month: string | null;
  dry_run_value: string | null;
  dry_run_reason: string;
  non_ledger: boolean;
}

export interface PersonalValue {
  key: string;
  definition_id: string;
  name: string;
  display: KpiDisplay;
  direction: string;
  nature: "ACTUAL";
  value: string | null;
  unit: string;
  nm_reason: string;
  non_ledger: boolean;
}

export interface MetricValue {
  month: string;
  value: string;
  version: number;
  note: string;
  entered_by: string;
  entered_at: string;
}

export interface OperationalMetric {
  id: string;
  key: string;
  name: string;
  unit: "count" | "EUR";
  aggregation: "LAST" | "SUM";
  source: "MANUAL";
  nature: "ACTUAL";
  non_ledger: true;
  values: MetricValue[];
}

export function useCustomKpis() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["custom-kpis", entityId],
    queryFn: () => api<CustomKpi[]>(`${base}/custom-kpis`),
  });
}

export function usePersonalKpis(runId: string | null) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["custom-kpis", entityId, "personal", runId],
    queryFn: () => api<PersonalValue[]>(`${base}/kpi-sets/${runId}/personal`),
    enabled: !!runId,
  });
}

export function useOperationalMetrics() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["operational-metrics", entityId],
    queryFn: () => api<OperationalMetric[]>(`${base}/operational-metrics`),
  });
}

export function useCustomKpiMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () =>
    client.invalidateQueries({ queryKey: ["custom-kpis", entityId] });
  return {
    check: useMutation({
      mutationFn: (body: { formula: string; display: KpiDisplay }) =>
        api<FormulaCheck>(`${base}/custom-kpis/check`, {
          method: "POST",
          body,
        }),
    }),
    create: useMutation({
      mutationFn: (body: CustomKpiIn & { scope: "PERSONAL" | "WORKSPACE" }) =>
        api<CustomKpi>(`${base}/custom-kpis`, { method: "POST", body }),
      onSuccess: refresh,
    }),
    revise: useMutation({
      mutationFn: ({ id, body }: { id: string; body: CustomKpiIn }) =>
        api<CustomKpi>(`${base}/custom-kpis/${id}/revise`, {
          method: "POST",
          body,
        }),
      onSuccess: refresh,
    }),
    decide: useMutation({
      mutationFn: ({
        id,
        approve,
        comment,
      }: {
        id: string;
        approve: boolean;
        comment: string;
      }) =>
        api<CustomKpi>(
          `${base}/custom-kpis/${id}/${approve ? "approve" : "reject"}`,
          {
            method: "POST",
            body: { comment },
          },
        ),
      onSuccess: refresh,
    }),
    retire: useMutation({
      mutationFn: (id: string) =>
        api<CustomKpi>(`${base}/custom-kpis/${id}/retire`, {
          method: "POST",
          body: {},
        }),
      onSuccess: refresh,
    }),
  };
}

export function useMetricMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () =>
    client.invalidateQueries({ queryKey: ["operational-metrics", entityId] });
  return {
    create: useMutation({
      mutationFn: (body: {
        key: string;
        name: string;
        unit: "count" | "EUR";
        aggregation: "LAST" | "SUM";
      }) =>
        api<OperationalMetric>(`${base}/operational-metrics`, {
          method: "POST",
          body,
        }),
      onSuccess: refresh,
    }),
    setValue: useMutation({
      mutationFn: ({
        metricId,
        month,
        value,
        note,
      }: {
        metricId: string;
        month: string;
        value: string;
        note: string;
      }) =>
        api<MetricValue>(`${base}/operational-metrics/${metricId}/values`, {
          method: "PUT",
          body: { month, value, note },
        }),
      onSuccess: refresh,
    }),
  };
}
