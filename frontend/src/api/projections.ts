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
