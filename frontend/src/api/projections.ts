// Assumption sets (M6-2).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { useScope } from "./hooks";

export type SetStatus = "DRAFT" | "APPROVED" | "SUPERSEDED";
export type StartFrom = "ACTUALS" | "BUDGET" | "EMPTY";

export interface AssumptionSet {
  id: string;
  family_id: string;
  version: number;
  name: string;
  cutover: string;
  months: number;
  start_from: StartFrom;
  note: string;
  status: SetStatus;
  supersedes_id: string | null;
  created_at: string;
  approved_at: string | null;
}

export interface GridRow {
  driver: string;
  line: string;
  unit: "AMOUNT" | "PERCENT" | "DAYS" | "MONTHS";
  values: string[];
  sources: ("ACTUALS" | "BUDGET" | "DEFAULT" | "MANUAL")[];
}

export interface AssumptionGrid {
  assumption_set: AssumptionSet;
  months: string[];
  rows: GridRow[];
  nature: "FORECAST";
}

export interface Change {
  driver: string;
  line: string;
  month: string;
  value: string;
}

export function useAssumptionSets() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["assumptions", entityId],
    queryFn: () => api<AssumptionSet[]>(`${base}/assumption-sets`),
  });
}

export function useAssumptionGrid(id: string | null) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["assumptions", entityId, id],
    queryFn: () => api<AssumptionGrid>(`${base}/assumption-sets/${id}`),
    enabled: !!id,
  });
}

export function useAssumptionMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () =>
    client.invalidateQueries({ queryKey: ["assumptions", entityId] });
  const url = (id: string, action = "") =>
    `${base}/assumption-sets/${id}${action}`;
  return {
    create: useMutation({
      mutationFn: (body: {
        name: string;
        cutover: string;
        months: number;
        start_from: StartFrom;
        revenue_growth: string;
      }) =>
        api<AssumptionSet>(`${base}/assumption-sets`, {
          method: "POST",
          body,
        }),
      onSuccess: refresh,
    }),
    save: useMutation({
      mutationFn: ({ id, changes }: { id: string; changes: Change[] }) =>
        api<AssumptionGrid>(url(id, "/values"), {
          method: "PUT",
          body: { changes },
        }),
      onSuccess: refresh,
    }),
    approve: useMutation({
      mutationFn: (id: string) =>
        api<AssumptionSet>(url(id, "/approve"), { method: "POST", body: {} }),
      onSuccess: refresh,
    }),
    revise: useMutation({
      mutationFn: (id: string) =>
        api<AssumptionSet>(url(id, "/revise"), { method: "POST", body: {} }),
      onSuccess: refresh,
    }),
  };
}

// Projections (M6-3), rolling forecasts (M6-4) and the full-year outlook (M6-5).

export type Granularity = "MONTH" | "QUARTER" | "YEAR";

export interface ProjectionRun {
  id: string;
  status: "VALID" | "INVALID" | "FAILED";
  as_of_date: string;
  assumption_set_id: string | null;
  actuals_watermark: number;
  input_hash: string;
  output_hash: string;
  invariants: Record<string, boolean>;
  error: string;
  stale: boolean;
  is_published: boolean;
  created_at: string;
}

export interface ProjectionStatements {
  projection: ProjectionRun;
  columns: { start: string; end: string; nature: "ACTUAL" | "FORECAST" }[];
  rows: Record<string, (string | null)[]>;
  failures: string[];
  result_ids: Record<string, (string | null)[]>;
}

export interface RollingForecast {
  configured: boolean;
  family_id: string | null;
  assumption_set_id: string | null;
  horizon: number | null;
  active: boolean;
  latest: ProjectionRun | null;
  stale: boolean;
  stale_reasons: string[];
  history: ProjectionRun[];
}

export interface AccuracyComparison {
  months_before: number;
  run_id: string;
  forecast: string;
  error: string;
  error_pct: string | null;
}

export interface AccuracyMonth {
  month: string;
  actual: Record<string, string>;
  comparisons: Record<string, AccuracyComparison[]>;
}

export interface Outlook {
  year_start: string;
  cutover: string | null;
  projection_id: string | null;
  note: string;
  columns: {
    start: string;
    end: string;
    granularity: Granularity;
    nature: "" | "ACTUAL" | "FORECAST" | "ACTUAL+FORECAST";
  }[];
  rows: Record<string, (string | null)[]>;
}

export function useProjections() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["projections", entityId],
    queryFn: () => api<ProjectionRun[]>(`${base}/projections`),
  });
}

export function useProjection(id: string | null, granularity: Granularity) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["projections", entityId, id, granularity],
    queryFn: () =>
      api<ProjectionStatements>(`${base}/projections/${id}`, {
        query: { granularity },
      }),
    enabled: !!id,
  });
}

export function useProjectionMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["projections", entityId] });
    void client.invalidateQueries({ queryKey: ["rolling", entityId] });
  };
  return {
    run: useMutation({
      mutationFn: (setId: string) =>
        api<ProjectionRun>(`${base}/projections`, {
          method: "POST",
          body: { assumption_set_id: setId },
        }),
      onSuccess: refresh,
    }),
    publish: useMutation({
      mutationFn: (id: string) =>
        api<unknown>(`${base}/calc-runs/${id}/publish`, {
          method: "POST",
          body: {},
        }),
      onSuccess: refresh,
    }),
  };
}

export function useRolling() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["rolling", entityId],
    queryFn: () => api<RollingForecast>(`${base}/rolling-forecast`),
  });
}

export function useRollingAccuracy(enabled: boolean) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["rolling", entityId, "accuracy"],
    queryFn: () => api<AccuracyMonth[]>(`${base}/rolling-forecast/accuracy`),
    enabled,
  });
}

export function useRollingMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["rolling", entityId] });
    void client.invalidateQueries({ queryKey: ["projections", entityId] });
  };
  return {
    configure: useMutation({
      mutationFn: (body: {
        assumption_set_id: string;
        horizon: number;
        active: boolean;
      }) =>
        api<RollingForecast>(`${base}/rolling-forecast`, {
          method: "PUT",
          body,
        }),
      onSuccess: refresh,
    }),
    refresh: useMutation({
      mutationFn: () =>
        api<RollingForecast>(`${base}/rolling-forecast/refresh`, {
          method: "POST",
          body: {},
        }),
      onSuccess: refresh,
    }),
  };
}

export function useOutlook(day: string) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["outlook", entityId, day],
    queryFn: () => api<Outlook>(`${base}/outlook`, { query: { day } }),
    enabled: !!day,
  });
}
