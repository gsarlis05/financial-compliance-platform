// Bringing existing books in (R-2, #245): templates, then each file checked (nothing kept) and
// imported. Accounts and customers or suppliers are created directly; opening balances and open
// invoices become one draft entry that is approved and posted as usual.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiUrl } from "./client";
import { useScope } from "./hooks";

export type ImportKind = "chart" | "counterparties" | "opening-balances";
export type TemplateKind = ImportKind | "open-items";

export interface ImportOutcome {
  kind: ImportKind;
  committed: boolean;
  rows: number;
  problems: { file: string; row: number; column: string; message: string }[];
  warnings: string[];
  unknown_accounts: { code: string; name: string; rows: number[] }[];
  unknown_counterparties: {
    name: string;
    side: "RECEIVABLE" | "PAYABLE" | "";
    rows: number[];
  }[];
  accounts: string[];
  counterparties: string[];
  skipped: string[];
  lines: {
    account_code: string;
    account_name: string;
    debit: string;
    credit: string;
    counterparty_code: string;
    reference: string;
    due_date: string | null;
  }[];
  total_debit: string;
  total_credit: string;
  entry_id: string | null;
  files: Record<string, string>;
}

export interface ImportRequest {
  file: File;
  commit: boolean;
  openItems?: File | null;
  agedReceivables?: File | null;
  agedPayables?: File | null;
  asOf?: string;
  accountMap?: Record<string, string>;
  resultsAccount?: string;
  dateOrder?: "day" | "month";
  createCounterparties?: boolean;
}

export interface ImportPreset {
  key: string;
  name: string;
  day_first: boolean;
  status: string;
  note: string;
}

export function useImportPresets() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["import-presets", entityId],
    queryFn: () => api<ImportPreset[]>(`${base}/imports/presets`),
    staleTime: Infinity,
  });
}

export function templateUrl(
  base: string,
  kind: TemplateKind,
  format: "xlsx" | "csv",
): string {
  return apiUrl(`${base}/imports/templates/${kind}`, { format });
}

export function useImport(kind: ImportKind) {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (req: ImportRequest) => {
      const body = new FormData();
      body.append("file", req.file);
      body.append("commit", req.commit ? "true" : "false");
      if (req.openItems) {
        body.append("open_items", req.openItems);
      }
      if (req.agedReceivables) {
        body.append("aged_receivables", req.agedReceivables);
      }
      if (req.agedPayables) {
        body.append("aged_payables", req.agedPayables);
      }
      if (req.resultsAccount) {
        body.append("results_account", req.resultsAccount);
      }
      if (req.dateOrder) {
        body.append("date_order", req.dateOrder);
      }
      if (req.createCounterparties) {
        body.append("create_counterparties", "true");
      }
      if (req.asOf) {
        body.append("as_of", req.asOf);
      }
      if (req.accountMap) {
        body.append("account_map", JSON.stringify(req.accountMap));
      }
      return api<ImportOutcome>(`${base}/imports/${kind}`, {
        method: "POST",
        body,
      });
    },
    onSuccess: (outcome) => {
      if (outcome.committed) {
        void client.invalidateQueries({ queryKey: ["accounts", entityId] });
        void client.invalidateQueries({
          queryKey: ["counterparties", entityId],
        });
        void client.invalidateQueries({ queryKey: ["entries", entityId] });
      }
    },
  });
}
