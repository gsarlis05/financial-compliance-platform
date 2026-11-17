// CFO dashboard (M4-8): response shapes and hooks.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { useScope } from "./hooks";

export type WidgetType =
  | "kpis"
  | "cash"
  | "budget"
  | "top_variances"
  | "goals"
  | "alerts"
  | "waterfall"
  | "scenario";
export const WIDGET_TYPES: WidgetType[] = [
  "kpis",
  "cash",
  "budget",
  "top_variances",
  "goals",
  "alerts",
  "waterfall",
  "scenario",
];

export interface LayoutItem {
  type: WidgetType;
  kpis?: string[];
  width?: "half";
  scenario_id?: string;
}

export type Preset = "MONTH" | "QTD" | "YTD" | "LTM";
export const PRESETS: Preset[] = ["MONTH", "QTD", "YTD", "LTM"];

export interface DashboardQuery {
  preset: Preset;
  month: string;
  comparison: "BUDGET" | "PRIOR_YEAR";
}

export interface KpiCard {
  key: string;
  name: string;
  name_el: string;
  display: string;
  direction: string;
  result_id: string;
  value: string | null;
  nm_reason: string;
  nature: string;
  comparison_value: string | null;
}

export interface CashWeek {
  label: string;
  start: string;
  end: string;
  closing: string;
  minimum: string;
}

export interface VarianceLine {
  line: string;
  dimension_value_id: string | null;
  direction: string;
  actual: string;
  actual_nature: string;
  comparison: string;
  comparison_nature: string;
  variance: string;
  percent: string | null;
  favourable: boolean | null;
  requires_explanation: boolean;
}

export interface GoalItem {
  id: string;
  name: string;
  metric_name: string;
  unit: string;
  display: string;
  period_end: string;
  target: string;
  direction: string;
  status: string | null;
  projected: string | null;
  as_of: string | null;
}

/* Widget data is typed per widget type; fields are absent when the widget is empty or denied. */
export interface WidgetData {
  run_id?: string;
  stale?: boolean;
  cards?: KpiCard[];
  as_of?: string;
  opening?: string;
  weeks?: CashWeek[];
  first_shortfall?: string | null;
  budget_name?: string;
  version_number?: number;
  unposted?: number | null;
  rows?: VarianceLine[];
  top?: VarianceLine[];
  goals?: GoalItem[];
  warning?: number;
  critical?: number;
  latest?: {
    id: string;
    title: string;
    severity: string;
    kind: string;
    created_at: string;
  }[];
  // waterfall (M8-4)
  start?: string;
  start_nature?: string;
  end?: string;
  end_nature?: string;
  steps?: { line: string; value: string; favourable: boolean | null }[];
  // scenario (M8-4)
  name?: string;
  base_name?: string;
  base_version?: number;
  nature?: string;
  engine_status?: string;
  changes?: Record<string, string>;
  lowest_cash?: { base: string; scenario: string };
}

export interface Widget {
  type: WidgetType;
  status: "ok" | "empty" | "denied";
  reason: string;
  options: { kpis?: string[]; width?: "half"; scenario_id?: string };
  data: WidgetData;
}

export interface Dashboard {
  period: {
    preset: string;
    month: string;
    date_from: string;
    date_to: string;
    fiscal_year_start: string;
    comparison: string;
  };
  layout_source: "USER" | "WORKSPACE" | "BUILT_IN";
  widgets: Widget[];
}

export function useDashboard(q: DashboardQuery) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["dashboard", entityId, q],
    queryFn: () => api<Dashboard>(`${base}/dashboard`, { query: { ...q } }),
  });
}

export function useDashboardMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () =>
    client.invalidateQueries({ queryKey: ["dashboard", entityId] });
  return {
    refresh: useMutation({
      mutationFn: (q: DashboardQuery) =>
        api<{ kpi_sets: number; alerts_raised: number }>(
          `${base}/dashboard/refresh`,
          { method: "POST", body: q },
        ),
      onSuccess: refresh,
    }),
    save: useMutation({
      mutationFn: ({
        widgets,
        asDefault,
      }: {
        widgets: LayoutItem[];
        asDefault: boolean;
      }) =>
        api(`${base}/dashboard-layout${asDefault ? "/default" : ""}`, {
          method: "PUT",
          body: { widgets },
        }),
      onSuccess: refresh,
    }),
    reset: useMutation({
      mutationFn: () => api(`${base}/dashboard-layout`, { method: "DELETE" }),
      onSuccess: refresh,
    }),
  };
}

// --- saved views (M8-4) ---------------------------------------------------------------------

export interface SavedView {
  id: string;
  name: string;
  preset: Preset;
  comparison: "BUDGET" | "PRIOR_YEAR";
}

export function useSavedViews() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () =>
    client.invalidateQueries({ queryKey: ["dashboard-views", entityId] });
  return {
    list: useQuery({
      queryKey: ["dashboard-views", entityId],
      queryFn: () => api<SavedView[]>(`${base}/dashboard-views`),
    }),
    save: useMutation({
      mutationFn: (body: Omit<SavedView, "id">) =>
        api<SavedView>(`${base}/dashboard-views`, { method: "PUT", body }),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: string) =>
        api(`${base}/dashboard-views/${id}`, { method: "DELETE" }),
      onSuccess: refresh,
    }),
  };
}
