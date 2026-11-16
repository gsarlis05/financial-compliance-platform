// Scenarios, sensitivity, working capital, goals against scenarios and projected KPIs (M7).
// Every figure these return is HYPOTHETICAL (a scenario) or FORECAST (an approved set).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { useScope } from "./hooks";

export type OverrideType =
  | "PCT_CHANGE"
  | "ABS_CHANGE"
  | "TIMING_SHIFT"
  | "NEW_DEBT"
  | "NEW_HIRE"
  | "CAPEX"
  | "ONE_OFF"
  | "RATE_CHANGE";

export const OVERRIDE_TYPES: OverrideType[] = [
  "PCT_CHANGE",
  "ABS_CHANGE",
  "TIMING_SHIFT",
  "NEW_DEBT",
  "NEW_HIRE",
  "CAPEX",
  "ONE_OFF",
  "RATE_CHANGE",
];

export type Params = Record<string, string | number | string[]>;

export interface Scenario {
  id: string;
  name: string;
  description: string;
  status: "DRAFT" | "SHARED" | "ARCHIVED";
  base_set_id: string;
  copied_from_id: string | null;
  created_by_id: string;
  created_at: string;
  shared_at: string | null;
  archived_at: string | null;
  nature: "HYPOTHETICAL";
}

export interface ScenarioOverride {
  id: string;
  seq: number;
  type: OverrideType;
  params: Params;
  rationale: string;
}

export interface ScenarioDetail {
  scenario: Scenario;
  base: {
    id: string;
    name: string;
    version: number;
    status: string;
    newer_version_approved: boolean;
    first_month: string;
    last_month: string;
    loans: string[];
  };
  overrides: ScenarioOverride[];
}

export interface ComparisonRow {
  key: string;
  base: (string | null)[];
  scenario: (string | null)[];
  difference: (string | null)[];
  overrides: string[][];
}

export interface Effect {
  override_id: string | null;
  seq: number | null;
  type: string;
  label: string;
  changes: Record<string, string>;
}

export interface Liquidity {
  lowest_cash: string;
  lowest_cash_month: string | null;
  first_negative_month: string | null;
  months_below_minimum: number;
  peak_facility: string;
  closing_debt: string;
}

export interface Comparison {
  scenario: Scenario;
  base: ScenarioDetail["base"];
  watermark: number;
  granularity: string;
  columns: { start: string; end: string; nature: string }[];
  rows: ComparisonRow[];
  effects: Effect[];
  liquidity: { base: Liquidity; scenario: Liquidity };
  valid: boolean;
  failures: string[];
  notes: string[];
  nature: "HYPOTHETICAL";
  engine_status: string;
}

export type Granularity = "MONTH" | "QUARTER" | "YEAR";

export function useScenarios() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["scenarios", entityId],
    queryFn: () => api<Scenario[]>(`${base}/scenarios`),
  });
}

export function useScenario(id: string | null) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["scenario", entityId, id],
    queryFn: () => api<ScenarioDetail>(`${base}/scenarios/${id}`),
    enabled: !!id,
  });
}

export function useComparison(
  id: string | null,
  granularity: Granularity,
  on: boolean,
) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["comparison", entityId, id, granularity],
    queryFn: () =>
      api<Comparison>(`${base}/scenarios/${id}/comparison`, {
        query: { granularity },
      }),
    enabled: !!id && on,
    retry: false,
  });
}

export function useScenarioMutations(id: string | null) {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["scenarios", entityId] });
    void client.invalidateQueries({ queryKey: ["scenario", entityId] });
    void client.invalidateQueries({ queryKey: ["comparison", entityId] });
  };
  const url = `${base}/scenarios/${id}`;
  return {
    create: useMutation({
      mutationFn: (body: {
        name: string;
        base_set_id: string;
        description: string;
      }) => api<Scenario>(`${base}/scenarios`, { method: "POST", body }),
      onSuccess: refresh,
    }),
    addOverride: useMutation({
      mutationFn: (body: {
        type: OverrideType;
        params: Params;
        rationale: string;
      }) => api<ScenarioOverride>(`${url}/overrides`, { method: "POST", body }),
      onSuccess: refresh,
    }),
    removeOverride: useMutation({
      mutationFn: (overrideId: string) =>
        api<null>(`${url}/overrides/${overrideId}`, { method: "DELETE" }),
      onSuccess: refresh,
    }),
    action: useMutation({
      mutationFn: (what: "share" | "archive") =>
        api<Scenario>(`${url}/${what}`, { method: "POST", body: {} }),
      onSuccess: refresh,
    }),
    copy: useMutation({
      mutationFn: (body: { name?: string; base_set_id?: string }) =>
        api<Scenario>(`${url}/copy`, { method: "POST", body }),
      onSuccess: refresh,
    }),
    saveRun: useMutation({
      mutationFn: () =>
        api<{ id: string; status: string; output_hash: string | null }>(
          `${url}/runs`,
          { method: "POST", body: {} },
        ),
    }),
    promote: useMutation({
      mutationFn: (name: string) =>
        api<{ assumption_set_id: string; name: string; status: string }>(
          `${url}/promote`,
          { method: "POST", body: name ? { name } : {} },
        ),
      onSuccess: () => {
        void client.invalidateQueries({ queryKey: ["assumptions", entityId] });
      },
    }),
  };
}

// --- sensitivity and tornado (M7-3) ------------------------------------------------------------

export type SensitivityOutput =
  | "MIN_CASH"
  | "CLOSING_CASH"
  | "FIRST_SHORTFALL"
  | "EBITDA"
  | "NET_INCOME";

export interface AnalysisBase {
  base_set_id?: string;
  scenario_id?: string;
  output: SensitivityOutput;
  year?: number | null;
}

export interface Measure {
  value: string;
  month: string | null;
}

export interface Analysis {
  kind: "ONE_VARIABLE" | "TORNADO";
  output: SensitivityOutput;
  year: number | null;
  base_label: string;
  base: Measure;
  points: { shock: string; result: Measure; change: string }[];
  bars: {
    driver: string;
    label: string;
    low: Measure;
    high: Measure;
    swing: string;
  }[];
  input_hash: string;
  watermark: number;
  cached: boolean;
  nature: "HYPOTHETICAL";
  engine_status: string;
}

export function useSensitivity() {
  const { base } = useScope();
  return {
    oneVariable: useMutation({
      mutationFn: (
        body: AnalysisBase & {
          driver: string;
          unit: "PERCENT" | "DAYS";
          low: string;
          high: string;
          steps: number;
        },
      ) =>
        api<Analysis>(`${base}/sensitivity/one-variable`, {
          method: "POST",
          body,
        }),
    }),
    tornado: useMutation({
      mutationFn: (
        body: AnalysisBase & { drivers: string[]; percent: string },
      ) =>
        api<Analysis>(`${base}/sensitivity/tornado`, { method: "POST", body }),
    }),
  };
}

// --- working capital (M7-4) --------------------------------------------------------------------

export interface WorkingCapitalMonth {
  month: string;
  receivables: string;
  inventory: string;
  payables: string;
  net: string;
  change: string;
  cash_effect: string;
  dso: string;
  dio: string;
  dpo: string;
  ccc: string;
}

export interface WorkingCapital {
  base_label: string;
  nature: string;
  watermark: number;
  cutover: string;
  observed: Record<string, string>;
  observed_ccc: string;
  months: WorkingCapitalMonth[];
  engine_status: string;
}

export interface DaysWorth {
  driver: string;
  days: number;
  closing_cash_change: string;
  lowest_cash_change: string;
  net_working_capital_change: string;
  by_month: { month: string; cash_change: string }[];
  nature: "HYPOTHETICAL";
}

export interface BaseChoice {
  base_set_id?: string;
  scenario_id?: string;
}

export function useWorkingCapital(choice: BaseChoice | null) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["working-capital", entityId, choice],
    queryFn: () =>
      api<WorkingCapital>(`${base}/working-capital`, { query: { ...choice } }),
    enabled: !!choice && !!(choice.base_set_id || choice.scenario_id),
    retry: false,
  });
}

export function useDaysWorth() {
  const { base } = useScope();
  return useMutation({
    mutationFn: (
      body: BaseChoice & { driver: "dso" | "dio" | "dpo"; days: number },
    ) =>
      api<DaysWorth>(`${base}/working-capital/days-worth`, {
        method: "POST",
        body,
      }),
  });
}

// --- goals against scenarios (M7-5) and projected KPIs (M7-6) ----------------------------------

export interface GoalOutlook {
  label: string;
  applicable: boolean;
  reason: string;
  status: string;
  method: string;
  note: string;
  nature: string;
  projected: string | null;
  gap: string | null;
}

export function useGoalOutlooks(goalId: string | null, scenarioIds: string[]) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["goal-outlooks", entityId, goalId, scenarioIds],
    queryFn: () =>
      api<GoalOutlook[]>(`${base}/goals/${goalId}/scenario-outlooks`, {
        query: { scenario_ids: scenarioIds.join(",") },
      }),
    enabled: !!goalId && scenarioIds.length > 0,
    retry: false,
  });
}

export interface ProjectedKpis {
  label: string;
  nature: string;
  library: string;
  year: number;
  start: string;
  end: string;
  kpis: {
    key: string;
    name: string;
    display: string;
    value: string | null;
    nm_reason: string;
    base_value: string | null;
  }[];
  engine_status: string;
}

export function useProjectedKpis(
  choice: BaseChoice | null,
  year: number | null,
) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["projected-kpis", entityId, choice, year],
    queryFn: () =>
      api<ProjectedKpis>(`${base}/projected-kpis`, {
        query: { ...choice, year },
      }),
    enabled: !!choice && !!year,
    retry: false,
  });
}
