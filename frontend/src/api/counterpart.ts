// Counterpart hints between a business and the owner's personal books (M5-3).
// Each request stays in one workspace: business lines are read from the business workspace with
// the person's own permission there; decisions are stored in the personal workspace.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { useScope } from "./hooks";
import type { Account, AccountLedger } from "./types";

export interface CounterpartLink {
  id: string;
  business_slug: string;
  business_entity_id: string;
  business_account_id: string;
  label: string;
  account_id: string;
  category_id: string;
  since: string;
  created_at: string;
}

export interface CounterpartDecision {
  id: string;
  business_entry_id: string;
  decision: "CONFIRMED" | "DISMISSED";
  amount: string;
  entry_date: string;
  personal_entry_id: string | null;
  created_at: string;
}

export interface DecisionIn {
  business_entry_id: string;
  date: string;
  amount: string;
  description: string;
}

export function useCounterpartLinks() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["personal", entityId, "counterpart-links"],
    queryFn: () => api<CounterpartLink[]>(`${base}/personal/counterpart-links`),
  });
}

export function useCounterpartDecisions(linkId: string) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["personal", entityId, "counterpart-decisions", linkId],
    queryFn: () =>
      api<CounterpartDecision[]>(
        `${base}/personal/counterpart-links/${linkId}/decisions`,
      ),
  });
}

/** Accounts of a business entity, read in that business workspace. */
export function useBusinessAccounts(slug: string, entityId: string) {
  return useQuery({
    queryKey: ["accounts", entityId],
    queryFn: () => api<Account[]>(`/w/${slug}/entities/${entityId}/accounts`),
    enabled: !!slug && !!entityId,
  });
}

/** The linked account's general ledger, read in the business workspace. */
export function useBusinessLedger(link: CounterpartLink, dateTo: string) {
  return useQuery({
    queryKey: [
      "general-ledger",
      link.business_entity_id,
      link.business_account_id,
      link.since,
      dateTo,
    ],
    queryFn: () =>
      api<AccountLedger>(
        `/w/${link.business_slug}/entities/${link.business_entity_id}/reports/general-ledger/${link.business_account_id}`,
        { query: { date_from: link.since, date_to: dateTo } },
      ),
    retry: false,
  });
}

export function useCounterpartMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () =>
    client.invalidateQueries({ queryKey: ["personal", entityId] });
  const links = `${base}/personal/counterpart-links`;
  return {
    link: useMutation({
      mutationFn: (body: Omit<CounterpartLink, "id" | "created_at">) =>
        api<CounterpartLink>(links, { method: "POST", body }),
      onSuccess: refresh,
    }),
    revoke: useMutation({
      mutationFn: (id: string) =>
        api<null>(`${links}/${id}/revoke`, { method: "POST", body: {} }),
      onSuccess: refresh,
    }),
    decide: useMutation({
      mutationFn: ({
        id,
        action,
        body,
      }: {
        id: string;
        action: "confirm" | "dismiss";
        body: DecisionIn;
      }) =>
        api<CounterpartDecision>(`${links}/${id}/${action}`, {
          method: "POST",
          body,
        }),
      onSuccess: refresh,
    }),
  };
}
