import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useParams } from "react-router";
import { api, newIdempotencyKey } from "./client";
import type {
  Account,
  Ageing,
  Counterparty,
  CounterpartyKind,
  Dimension,
  DimensionKind,
  DimensionValue,
  EntryInput,
  FiscalYear,
  IntegrityRun,
  JournalEntry,
  LegalEntity,
  Me,
  OpenItem,
  PeriodStatus,
  PeriodUnlock,
  Side,
  TrialBalance,
  Workspace,
} from "./types";

export function useScope(): { slug: string; entityId: string; base: string } {
  const { slug = "", entityId = "" } = useParams();
  return { slug, entityId, base: `/w/${slug}/entities/${entityId}` };
}

export const useMe = (): UseQueryResult<Me> =>
  useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/me"), retry: false });

export const useWorkspaces = () =>
  useQuery({ queryKey: ["workspaces"], queryFn: () => api<Workspace[]>("/workspaces") });

export const useWorkspace = (slug: string) =>
  useQuery({ queryKey: ["workspace", slug], queryFn: () => api<Workspace>(`/w/${slug}`), enabled: !!slug });

export const useEntities = (slug: string) =>
  useQuery({
    queryKey: ["entities", slug],
    queryFn: () => api<LegalEntity[]>(`/w/${slug}/entities`),
    enabled: !!slug,
  });

export function useCreateWorkspace() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; kind: string; entity_name?: string }) =>
      api<Workspace>("/workspaces", { method: "POST", body }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["workspaces"] }),
  });
}

export function useAccounts() {
  const { base, entityId } = useScope();
  return useQuery({ queryKey: ["accounts", entityId], queryFn: () => api<Account[]>(`${base}/accounts`) });
}

export function useAccountMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: ["accounts", entityId] });
  return {
    applyTemplate: useMutation({
      mutationFn: (template: string) =>
        api<Account[]>(`${base}/accounts/apply-template`, { method: "POST", body: { template } }),
      onSuccess: refresh,
    }),
    create: useMutation({
      mutationFn: (body: { code: string; name: string; type: string; parent_code?: string }) =>
        api<Account>(`${base}/accounts`, { method: "POST", body }),
      onSuccess: refresh,
    }),
  };
}

export function useFiscalYears() {
  const { base, entityId } = useScope();
  return useQuery({ queryKey: ["fiscal-years", entityId], queryFn: () => api<FiscalYear[]>(`${base}/fiscal-years`) });
}

export function useUnlocks() {
  const { base, entityId } = useScope();
  return useQuery({ queryKey: ["unlocks", entityId], queryFn: () => api<PeriodUnlock[]>(`${base}/unlock-requests`) });
}

export function usePeriodMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["fiscal-years", entityId] });
    void client.invalidateQueries({ queryKey: ["unlocks", entityId] });
  };
  return {
    createYear: useMutation({
      mutationFn: (body: { start_date: string; months: number }) =>
        api<FiscalYear>(`${base}/fiscal-years`, { method: "POST", body }),
      onSuccess: refresh,
    }),
    setStatus: useMutation({
      mutationFn: ({ periodId, status }: { periodId: string; status: PeriodStatus }) =>
        api(`${base}/periods/${periodId}/status`, { method: "POST", body: { status } }),
      onSuccess: refresh,
    }),
    requestUnlock: useMutation({
      mutationFn: ({ periodId, reason }: { periodId: string; reason: string }) =>
        api(`${base}/periods/${periodId}/unlock-requests`, {
          method: "POST",
          body: { reason, window_minutes: 60 },
        }),
      onSuccess: refresh,
    }),
    decideUnlock: useMutation({
      mutationFn: ({ unlockId, decision }: { unlockId: string; decision: "approve" | "reject" }) =>
        api(`${base}/unlock-requests/${unlockId}/${decision}`, { method: "POST", body: {} }),
      onSuccess: refresh,
    }),
  };
}

export function useEntries(status?: string) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["entries", entityId, status ?? "all"],
    queryFn: () => api<JournalEntry[]>(`${base}/journal-entries`, { query: { status } }),
  });
}

export function useEntry(entryId: string) {
  const { base } = useScope();
  return useQuery({
    queryKey: ["entry", entryId],
    queryFn: () => api<JournalEntry>(`${base}/journal-entries/${entryId}`),
    enabled: !!entryId,
  });
}

export type EntryAction = "submit" | "approve" | "reject" | "post" | "void" | "reverse";

export function useEntryMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = (entry: JournalEntry) => {
    client.setQueryData(["entry", entry.id], entry);
    void client.invalidateQueries({ queryKey: ["entries", entityId] });
  };
  return {
    save: useMutation({
      mutationFn: ({ id, body }: { id?: string; body: EntryInput }) =>
        id
          ? api<JournalEntry>(`${base}/journal-entries/${id}`, { method: "PUT", body })
          : api<JournalEntry>(`${base}/journal-entries`, {
              method: "POST",
              body,
              idempotencyKey: newIdempotencyKey(),
            }),
      onSuccess: refresh,
    }),
    act: useMutation({
      mutationFn: ({ id, action, reason }: { id: string; action: EntryAction; reason?: string }) =>
        api<JournalEntry>(`${base}/journal-entries/${id}/${action}`, {
          method: "POST",
          body: reason ? { reason } : {},
          ...(action === "post" ? { idempotencyKey: newIdempotencyKey() } : {}),
        }),
      onSuccess: refresh,
    }),
  };
}

export function useTrialBalance(asOf: string, dimensionValueId = "") {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["trial-balance", entityId, asOf, dimensionValueId],
    queryFn: () =>
      api<TrialBalance>(`${base}/reports/trial-balance`, {
        query: { as_of: asOf, ...(dimensionValueId ? { dimension_value_id: dimensionValueId } : {}) },
      }),
    enabled: !!asOf,
  });
}

export function useDimensions() {
  const { base, entityId } = useScope();
  return useQuery({ queryKey: ["dimensions", entityId], queryFn: () => api<Dimension[]>(`${base}/dimensions`) });
}

export function useDimensionMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: ["dimensions", entityId] });
  return {
    createDimension: useMutation({
      mutationFn: (body: { code: string; name: string; kind: DimensionKind }) =>
        api<Dimension>(`${base}/dimensions`, { method: "POST", body }),
      onSuccess: refresh,
    }),
    createValue: useMutation({
      mutationFn: ({ dimensionId, ...body }: { dimensionId: string; code: string; name: string }) =>
        api<DimensionValue>(`${base}/dimensions/${dimensionId}/values`, { method: "POST", body }),
      onSuccess: refresh,
    }),
    setValueStatus: useMutation({
      mutationFn: ({ valueId, status }: { valueId: string; status: "ACTIVE" | "INACTIVE" }) =>
        api<DimensionValue>(`${base}/dimension-values/${valueId}`, { method: "PATCH", body: { status } }),
      onSuccess: refresh,
    }),
  };
}

export function useIntegrity(slug: string) {
  const client = useQueryClient();
  const runs = useQuery({
    queryKey: ["integrity", slug],
    queryFn: () => api<IntegrityRun[]>(`/w/${slug}/integrity-checks`),
  });
  const run = useMutation({
    mutationFn: () => api<IntegrityRun>(`/w/${slug}/integrity-checks`, { method: "POST", body: {} }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["integrity", slug] }),
  });
  return { runs, run };
}

export function useCounterparties() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["counterparties", entityId],
    queryFn: () => api<Counterparty[]>(`${base}/counterparties`),
  });
}

export function useCounterpartyMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  return {
    create: useMutation({
      mutationFn: (body: {
        code: string;
        name: string;
        kind: CounterpartyKind;
        vat_no: string;
        email: string;
        payment_terms_days: number;
      }) => api<Counterparty>(`${base}/counterparties`, { method: "POST", body }),
      onSuccess: () => client.invalidateQueries({ queryKey: ["counterparties", entityId] }),
    }),
  };
}

export function useAgeing(asOf: string, side: Side) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["ageing", entityId, asOf, side],
    queryFn: () => api<Ageing>(`${base}/reports/ageing`, { query: { as_of: asOf, side } }),
    enabled: !!asOf,
  });
}

export function useOpenItems(asOf: string, counterpartyId: string) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["open-items", entityId, asOf, counterpartyId],
    queryFn: () =>
      api<OpenItem[]>(`${base}/open-items`, { query: { as_of: asOf, counterparty_id: counterpartyId } }),
    enabled: !!asOf && !!counterpartyId,
  });
}

export function useAllocationMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["open-items", entityId] });
    void client.invalidateQueries({ queryKey: ["ageing", entityId] });
  };
  return {
    autoAllocate: useMutation({
      mutationFn: ({ counterpartyId, asOf }: { counterpartyId: string; asOf: string }) =>
        api<unknown[]>(`${base}/counterparties/${counterpartyId}/auto-allocate`, {
          method: "POST",
          body: { as_of: asOf },
        }),
      onSuccess: refresh,
    }),
    flag: useMutation({
      mutationFn: ({ lineId, disputed, note }: { lineId: string; disputed: boolean; note: string }) =>
        api<unknown>(`${base}/open-items/${lineId}/flag`, { method: "PUT", body: { disputed, note } }),
      onSuccess: refresh,
    }),
  };
}
