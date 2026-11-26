// Recognising a bank's CSV export (R-1, #244): the layout read from the file, with questions
// where the file leaves something open, a preview, and saving it as the account's mapping.
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "./client";
import { useScope } from "./hooks";

export interface BankPreset {
  key: string;
  name: string;
  status: string;
  note: string;
}

export interface CsvMapping {
  date: string;
  amount: string;
  debit: string;
  credit: string;
  description: string;
  reference: string;
  counterparty: string;
  balance: string;
  date_format: string;
  delimiter: string;
  decimal_comma: boolean;
  has_header: boolean;
  encoding: string;
  skip_rows: number;
}

export interface CsvDetection {
  mapping: CsvMapping;
  columns: Record<string, string>;
  questions: {
    field: "date_format" | "decimal_comma";
    message: string;
    options: string[];
    chosen: string;
  }[];
  preview: {
    booking_date: string;
    amount: string;
    description: string;
    reference: string;
    counterparty_name: string;
  }[];
  preset: BankPreset | null;
  error: string;
}

export function useBankPresets() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["bank-presets", entityId],
    queryFn: () => api<BankPreset[]>(`${base}/bank-presets`),
    staleTime: Infinity,
  });
}

export function useCsvLayout(accountId: string) {
  const { base } = useScope();
  const url = `${base}/bank-accounts/${accountId}`;
  return {
    detect: useMutation({
      mutationFn: ({ file, preset }: { file: File; preset: string }) => {
        const body = new FormData();
        body.append("file", file);
        body.append("preset", preset);
        return api<CsvDetection>(`${url}/csv-detect`, { method: "POST", body });
      },
    }),
    save: useMutation({
      mutationFn: (mapping: CsvMapping) =>
        api<unknown>(`${url}/csv-mapping`, { method: "PUT", body: mapping }),
    }),
  };
}
