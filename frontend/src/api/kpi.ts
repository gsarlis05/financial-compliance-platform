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
