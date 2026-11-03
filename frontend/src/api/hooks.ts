import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useParams } from "react-router";
import { api, newIdempotencyKey } from "./client";
import type {
  Account,
  EntryInput,
  FiscalYear,
  IntegrityRun,
  JournalEntry,
  LegalEntity,
  Me,
  PeriodStatus,
  PeriodUnlock,
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

export function useTrialBalance(asOf: string) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["trial-balance", entityId, asOf],
    queryFn: () => api<TrialBalance>(`${base}/reports/trial-balance`, { query: { as_of: asOf } }),
    enabled: !!asOf,
  });
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
