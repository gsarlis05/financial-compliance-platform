// Help for data entry (V1-2i, #231): favourite VAT codes per user and company, how often each code
// is used, each account's usual code, and typing suggestions from the company's own entries.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { api } from "./client";
import { useScope } from "./hooks";

export type SuggestField = "description" | "memo" | "reference";

export interface EntryHelpers {
  favourites: string[];
  toggleFavourite: (vatCodeId: string, on: boolean) => void;
  /** Uses of each VAT code in this company. */
  uses: Record<string, number>;
  /** Each account's most used VAT code. */
  usual: Record<string, string>;
  suggest: (field: SuggestField, text: string) => Promise<Suggestion[]>;
}

export interface Suggestion {
  value: string;
  uses: number;
  last_used: string;
}

interface Usage {
  codes: { vat_code_id: string; uses: number }[];
  accounts: { account_id: string; vat_code_id: string; uses: number }[];
}

export function useEntryHelpers(): EntryHelpers {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const favKey = ["vat-favourites", entityId];
  const favourites = useQuery({
    queryKey: favKey,
    queryFn: () => api<{ vat_code_ids: string[] }>(`${base}/vat-favourites`),
  });
  const usage = useQuery({
    queryKey: ["vat-usage", entityId],
    queryFn: () => api<Usage>(`${base}/vat-usage`),
    staleTime: 60_000,
  });
  // Stable, so a field's suggestions are asked for only when its text changes.
  const suggest = useCallback(
    (field: SuggestField, text: string) =>
      api<Suggestion[]>(`${base}/entry-suggestions`, {
        query: { field, q: text, limit: "8" },
      }),
    [base],
  );
  const toggle = useMutation({
    mutationFn: ({ id, on }: { id: string; on: boolean }) =>
      api<{ vat_code_ids: string[] }>(
        `${base}/vat-favourites/${encodeURIComponent(id)}`,
        { method: on ? "PUT" : "DELETE", ...(on ? { body: {} } : {}) },
      ),
    onSuccess: (data) => client.setQueryData(favKey, data),
  });
  return {
    favourites: favourites.data?.vat_code_ids ?? [],
    toggleFavourite: (id, on) => toggle.mutate({ id, on }),
    uses: Object.fromEntries(
      (usage.data?.codes ?? []).map((c) => [c.vat_code_id, c.uses]),
    ),
    usual: Object.fromEntries(
      (usage.data?.accounts ?? []).map((a) => [a.account_id, a.vat_code_id]),
    ),
    suggest,
  };
}
