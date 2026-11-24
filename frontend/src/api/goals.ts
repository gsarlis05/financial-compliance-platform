// Goals (M4-6): response shapes and hooks.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./client";
import { useScope } from "./hooks";

export type GoalStatus = "ON_TRACK" | "AT_RISK" | "OFF_TRACK" | "UNDETERMINED";
export type TargetType =
  | "ABSOLUTE"
  | "CHANGE_PCT"
  | "MAINTAIN_MIN"
  | "MAINTAIN_MAX";

export interface GoalMetric {
  key: string;
  ref: string;
  name: string;
  name_el: string;
  kind: "ADDITIVE" | "RATIO" | "BALANCE";
  formula: string;
  direction: string;
  unit: string;
  display: string;
  convention: string;
}

export interface GoalVersion {
  id: string;
  number: number;
  target_type: TargetType;
  target_input: string;
  target_value: string;
  direction: "AT_LEAST" | "AT_MOST";
  materiality: string;
  owner_id: string;
  driver: string;
  baseline_value: string | null;
  baseline_nm_reason: string;
  baseline_from: string;
  baseline_to: string;
  baseline_run_id: string;
  reason: string;
  created_at: string;
  superseded_at: string | null;
}

export interface Goal {
  id: string;
  name: string;
  metric: string;
  metric_name: string;
  metric_kind: GoalMetric["kind"];
  metric_ref: string;
  unit: string;
  display: string;
  period_start: string;
  period_end: string;
  status: "ACTIVE" | "RETIRED";
  current: GoalVersion;
  versions: GoalVersion[];
  latest: {
    run_id: string;
    as_of: string;
    status: GoalStatus;
    projected: string | null;
    gap: string | null;
    breach_date: string | null;
    method: string;
    created_at: string;
  } | null;
}

export interface GoalFigure {
  result_id: string;
  key: string;
  dimensions: string[];
  period_start: string;
  period_end: string;
  granularity: string;
  nature: string;
  value: string | null;
  unit: string;
  nm_reason: string;
}

export interface GoalEvaluation {
  goal_id: string;
  version: number;
  run_id: string;
  run_status: string;
  watermark: number;
  as_of: string;
  cut_over: string;
  status: GoalStatus;
  method: string;
  method_note: string;
  out_of_date: boolean;
  figures: GoalFigure[];
  history: {
    as_of: string;
    status: GoalStatus;
    projected: string | null;
    gap: string | null;
    created_at: string;
  }[];
}

export interface GoalIn {
  name: string;
  metric: string;
  period_start: string;
  period_end: string;
  target_type: TargetType;
  target: string;
  materiality: string;
  driver: string;
}

export function useGoalMetrics() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["goal-metrics", entityId],
    queryFn: () => api<GoalMetric[]>(`${base}/goal-metrics`),
    staleTime: 300_000,
  });
}

export function useGoals(includeRetired: boolean) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["goals", entityId, includeRetired],
    queryFn: () =>
      api<Goal[]>(`${base}/goals`, {
        query: { include_retired: String(includeRetired) },
      }),
  });
}

/** The goal's latest evaluation, or null before the first one (404). */
export function useLatestEvaluation(goalId: string | null) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["goal-evaluation", entityId, goalId],
    enabled: goalId !== null,
    queryFn: async () => {
      try {
        return await api<GoalEvaluation>(
          `${base}/goals/${goalId ?? ""}/evaluations/latest`,
        );
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
  });
}

export function useGoalMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () =>
    client.invalidateQueries({ queryKey: ["goals", entityId] });
  return {
    create: useMutation({
      mutationFn: (body: GoalIn) =>
        api<Goal>(`${base}/goals`, { method: "POST", body }),
      onSuccess: refresh,
    }),
    revise: useMutation({
      mutationFn: ({
        id,
        body,
      }: {
        id: string;
        body: {
          target_type: TargetType;
          target: string;
          reason: string;
          materiality: string;
          driver: string;
        };
      }) => api<Goal>(`${base}/goals/${id}/versions`, { method: "POST", body }),
      onSuccess: refresh,
    }),
    retire: useMutation({
      mutationFn: (id: string) =>
        api<Goal>(`${base}/goals/${id}/retire`, { method: "POST", body: {} }),
      onSuccess: refresh,
    }),
    evaluate: useMutation({
      mutationFn: ({
        id,
        as_of,
        driver,
      }: {
        id: string;
        as_of: string;
        driver: string;
      }) =>
        api<GoalEvaluation>(`${base}/goals/${id}/evaluations`, {
          method: "POST",
          body: { as_of: as_of || null, driver },
        }),
      onSuccess: (made) => {
        client.setQueryData(["goal-evaluation", entityId, made.goal_id], made);
        void refresh();
      },
    }),
  };
}
