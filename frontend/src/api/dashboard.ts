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
  | "alerts";
export const WIDGET_TYPES: WidgetType[] = [
  "kpis",
  "cash",
  "budget",
  "top_variances",
  "goals",
  "alerts",
];

export interface LayoutItem {
  type: WidgetType;
  kpis?: string[];
}

export interface DashboardQuery {
  preset: "MONTH" | "QTD" | "YTD";
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
}

export interface Widget {
  type: WidgetType;
  status: "ok" | "empty" | "denied";
  reason: string;
  options: { kpis?: string[] };
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
