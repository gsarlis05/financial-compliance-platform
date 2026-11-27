// Correcting the rules on a screen (brief 27, T-2, #255): the VAT codes, the VAT return's box
// rules and the corporate tax rules in force, and corrections for this entity from a date, each
// with its source. Corrections are never edited; a later one replaces an earlier one.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { useScope } from "./hooks";
import type { VatCode } from "./types";

export interface Correction {
  id: string;
  kind: "VAT_CODE" | "VAT_BOX_RULE" | "CORPORATE_TAX";
  target: string;
  effective_from: string;
  values: Record<string, unknown>;
  source: string;
  note: string;
  created_at: string;
  created_by: string;
}

export interface BoxRule {
  category: string;
  line: "OUTPUT_VAT" | "INPUT_VAT" | "NET_SALE" | "NET_PURCHASE";
  status: "MAPPED" | "EXCLUDED" | "UNSUPPORTED";
  boxes: string[];
  reason: string;
  corrected_from: string | null;
}

export function useCodesOn(on: string) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["vat-codes", entityId, on],
    queryFn: () => api<VatCode[]>(`${base}/vat-codes`, { query: { on } }),
  });
}

export function useBoxRules(on: string) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["vat-box-rules", entityId, on],
    queryFn: () => api<BoxRule[]>(`${base}/vat-box-rules`, { query: { on } }),
  });
}

export function useCorrections() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["rule-corrections", entityId],
    queryFn: () => api<Correction[]>(`${base}/rule-corrections`),
  });
}

export function useCorrect() {
  const { base } = useScope();
  const client = useQueryClient();
  const done = () =>
    Promise.all(
      ["vat-codes", "vat-box-rules", "rule-corrections", "tax-rules"].map((k) =>
        client.invalidateQueries({ queryKey: [k] }),
      ),
    );
  return {
    vatCode: useMutation({
      mutationFn: ({
        code,
        ...body
      }: { code: string } & Record<string, unknown>) =>
        api<unknown>(
          `${base}/vat-codes/${encodeURIComponent(code)}/corrections`,
          {
            method: "POST",
            body,
          },
        ),
      onSuccess: done,
    }),
    boxRule: useMutation({
      mutationFn: (body: Record<string, unknown>) =>
        api<unknown>(`${base}/vat-box-rules/corrections`, {
          method: "POST",
          body,
        }),
      onSuccess: done,
    }),
    corporateTax: useMutation({
      mutationFn: (body: Record<string, unknown>) =>
        api<unknown>(`${base}/tax-rules/corrections`, { method: "POST", body }),
      onSuccess: done,
    }),
  };
}
