// The 13-week cash forecast (M3-7 … M3-10): response shapes and hooks.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./client";
import { useScope } from "./hooks";

export type Nature =
  | "ACTUAL"
  | "COMMITTED"
  | "EXPECTED"
  | "HYPOTHETICAL"
  | "BUDGET"
  | "FORECAST"
  | "TARGET";

export interface ForecastFlow {
  direction: "IN" | "OUT";
  category: string;
  nature: Nature;
  amount: string;
}

export interface ForecastWeek {
  index: number;
  label: string;
  start: string;
  end: string;
  opening: string;
  opening_nature: Nature;
  inflows: string;
  outflows: string;
  net: string;
  closing: string;
  minimum: string;
  headroom: string;
  undrawn_facilities: string;
  liquidity: string;
  shortfall: boolean;
  nature: Nature;
  flows: ForecastFlow[];
}

export interface ForecastWarning {
  code: string;
  message: string;
}

export interface Shortfall {
  date: string;
  balance: string;
}

export interface CashForecast {
  run_id: string;
  status: string;
  as_of: string;
  actuals_watermark: number;
  stale: boolean;
  stale_reasons: string[];
  created_at: string;
  opening_cash: string;
  overdue: string;
  beyond_horizon: string;
  first_shortfall: Shortfall | null;
  warnings: ForecastWarning[];
  weeks: ForecastWeek[];
}

export interface ForecastHistoryRow {
  run_id: string;
  as_of: string;
  created_at: string;
  status: string;
  stale: boolean;
  trigger: string;
  opening_cash: string;
  closing_week_13: string;
  first_shortfall: string | null;
}

export interface AccuracyComparison {
  horizon_weeks: number;
  run_id: string;
  forecast: string;
  error: string;
  ape_percent: string | null;
}

export interface ForecastAccuracy {
  weeks: {
    label: string;
    start: string;
    actual: string;
    comparisons: AccuracyComparison[];
  }[];
  mape_percent: Record<string, string | null>;
  samples: Record<string, number>;
  note: string;
}

export interface Override {
  type: "TIMING_SHIFT" | "PCT_CHANGE" | "ONE_OFF";
  party: string;
  category: string;
  days: number;
  percent: string;
  day: string | null;
  amount: string;
  reason: string;
}

export interface WhatIfWeek {
  label: string;
  start: string;
  base_closing: string;
  what_if_closing: string;
  delta: string;
  base_shortfall: boolean;
  what_if_shortfall: boolean;
}

export interface WhatIfResult {
  run_id: string;
  nature: "HYPOTHETICAL";
  saved: false;
  matched: number[];
  base_first_shortfall: Shortfall | null;
  what_if_first_shortfall: Shortfall | null;
  hypothetical_total: string;
  weeks: WhatIfWeek[];
}

export interface ForecastSettings {
  minimum_cash: string;
  unreconciled_warning_days: number;
  payables_policy: "DUE_DATE" | "WEEKDAY";
  payables_weekday: number;
}

export interface CalcResult {
  id: string;
  series_key: string;
  dimensions: string[];
  period_start: string;
  nature: Nature;
  value: string | null;
}

export interface CalcLineage {
  input_kind: string;
  input_ref: string;
  amount: string | null;
  note: string;
}

/** The latest forecast, or null when none has been run yet (404). */
export function useLatestForecast() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["cash-forecast", entityId, "latest"],
    queryFn: async () => {
      try {
        return await api<CashForecast>(`${base}/cash-forecasts/latest`);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          return null;
        }
        throw error;
      }
    },
  });
}

export function useForecastHistory() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["cash-forecast", entityId, "history"],
    queryFn: () =>
      api<ForecastHistoryRow[]>(`${base}/cash-forecasts/history?limit=20`),
  });
}

export function useForecastAccuracy(asOf: string) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["cash-forecast", entityId, "accuracy", asOf],
    queryFn: () =>
      api<ForecastAccuracy>(
        `${base}/cash-forecasts/accuracy?as_of=${asOf}&weeks=13`,
      ),
  });
}

export function useForecastSettings() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["cash-forecast", entityId, "settings"],
    queryFn: () => api<ForecastSettings>(`${base}/cash-forecast-settings`),
  });
}

/** A run's values, to drill from a week to the items behind a flow. */
export function useRunResults(runId: string | null) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["calc-run", entityId, runId],
    queryFn: () => api<{ results: CalcResult[] }>(`${base}/calc-runs/${runId}`),
    enabled: !!runId,
  });
}

export function useExplain(runId: string, resultId: string | null) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["calc-explain", entityId, runId, resultId],
    queryFn: () =>
      api<{ lineage: CalcLineage[] }>(
        `${base}/calc-runs/${runId}/results/${resultId}/explain`,
      ),
    enabled: !!resultId,
  });
}

export function useForecastMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () =>
    client.invalidateQueries({ queryKey: ["cash-forecast", entityId] });
  return {
    run: useMutation({
      mutationFn: () =>
        api<CashForecast>(`${base}/cash-forecasts`, {
          method: "POST",
          body: {},
        }),
      onSuccess: refresh,
    }),
    refreshNow: useMutation({
      mutationFn: () =>
        api<CashForecast | null>(`${base}/cash-forecasts/refresh`, {
          method: "POST",
          body: {},
        }),
      onSuccess: refresh,
    }),
    saveSettings: useMutation({
      mutationFn: (body: ForecastSettings) =>
        api<ForecastSettings>(`${base}/cash-forecast-settings`, {
          method: "PUT",
          body,
        }),
      onSuccess: refresh,
    }),
    whatIf: useMutation({
      mutationFn: ({
        runId,
        overrides,
      }: {
        runId: string;
        overrides: Override[];
      }) =>
        api<WhatIfResult>(`${base}/cash-forecasts/${runId}/what-if`, {
          method: "POST",
          body: { overrides },
        }),
    }),
  };
}
