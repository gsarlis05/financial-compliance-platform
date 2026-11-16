// Alerts (M4-7): response shapes and hooks.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { useScope } from "./hooks";

export interface Alert {
  id: string;
  key: string;
  kind: "GOAL_STATUS" | "GOAL_BREACH" | "BUDGET_OVERRUN" | "BUDGET_TREND";
  state: string;
  severity: "WARNING" | "CRITICAL";
  title: string;
  detail: string;
  subject_type: "goal" | "budget";
  subject_id: string;
  period: string | null;
  source_run_id: string | null;
  created_at: string;
  acknowledged_by_name: string;
  acknowledged_at: string | null;
  acknowledgement_note: string;
}

export function useAlerts(includeAcknowledged: boolean) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["alerts", entityId, includeAcknowledged],
    queryFn: () =>
      api<Alert[]>(`${base}/alerts`, {
        query: { include_acknowledged: String(includeAcknowledged) },
      }),
  });
}

export function useAlertMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () =>
    client.invalidateQueries({ queryKey: ["alerts", entityId] });
  return {
    check: useMutation({
      mutationFn: () =>
        api<{ raised: number }>(`${base}/alerts/check-budgets`, {
          method: "POST",
          body: {},
        }),
      onSuccess: refresh,
    }),
    acknowledge: useMutation({
      mutationFn: ({ id, note }: { id: string; note: string }) =>
        api<Alert>(`${base}/alerts/${id}/acknowledge`, {
          method: "POST",
          body: { note },
        }),
      onSuccess: refresh,
    }),
  };
}
