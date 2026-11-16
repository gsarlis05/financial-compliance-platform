// Personal finances (M5-1).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { useScope } from "./hooks";

export type MoneyType = "ASSET" | "LIABILITY" | "INCOME" | "EXPENSE";

export interface PersonalAccount {
  id: string;
  code: string;
  name: string;
  type: MoneyType;
  balance: string;
  amount: string;
  nature: "ACTUAL" | "EXPECTED";
  valuation_date: string | null;
}

export interface PersonalTransaction {
  entry_id: string;
  ref: string;
  date: string;
  description: string;
  kind: "SPENT" | "RECEIVED" | "MOVED" | "OPENING" | "UNDO" | "OTHER";
  amount: string;
  account_id: string | null;
  other_id: string | null;
  undone: boolean;
}

export interface NetWorth {
  as_of: string;
  assets: PersonalAccount[];
  liabilities: PersonalAccount[];
  total_assets: string;
  total_liabilities: string;
  net_worth: string;
  includes_valuations: boolean;
  trend: { date: string; net_worth: string; includes_valuations: boolean }[];
}

export interface Spending {
  date_from: string;
  date_to: string;
  income: { account_id: string; name: string; amount: string }[];
  spending: { account_id: string; name: string; amount: string }[];
  total_income: string;
  total_spending: string;
  left_over: string;
}

export interface TransactionIn {
  kind: "SPENT" | "RECEIVED" | "MOVED";
  date: string;
  amount: string;
  description: string;
  account_id: string;
  category_id?: string;
  to_account_id?: string;
}

export function usePersonalAccounts() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["personal", entityId, "accounts"],
    queryFn: () => api<PersonalAccount[]>(`${base}/personal/accounts`),
  });
}

export function useNetWorth() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["personal", entityId, "net-worth"],
    queryFn: () => api<NetWorth>(`${base}/personal/net-worth`),
  });
}

export function useTransactions(dateFrom: string, dateTo: string) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["personal", entityId, "transactions", dateFrom, dateTo],
    queryFn: () =>
      api<PersonalTransaction[]>(`${base}/personal/transactions`, {
        query: { date_from: dateFrom, date_to: dateTo },
      }),
  });
}

export function useSpending(dateFrom: string, dateTo: string) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["personal", entityId, "spending", dateFrom, dateTo],
    queryFn: () =>
      api<Spending>(`${base}/personal/spending`, {
        query: { date_from: dateFrom, date_to: dateTo },
      }),
  });
}

function usePost<T>(path: string) {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: object) =>
      api<T>(`${base}/personal/${path}`, { method: "POST", body }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["personal", entityId] }),
  });
}

export function usePersonalMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  return {
    setup: usePost<{ created: boolean }>("setup"),
    record: usePost<PersonalTransaction>("transactions"),
    opening: usePost<PersonalTransaction>("opening-balances"),
    valuation: usePost<object>("valuations"),
    account: usePost<PersonalAccount>("accounts"),
    undo: useMutation({
      mutationFn: ({ id, reason }: { id: string; reason: string }) =>
        api<PersonalTransaction>(`${base}/personal/transactions/${id}/undo`, {
          method: "POST",
          body: { reason },
        }),
      onSuccess: () =>
        client.invalidateQueries({ queryKey: ["personal", entityId] }),
    }),
  };
}
