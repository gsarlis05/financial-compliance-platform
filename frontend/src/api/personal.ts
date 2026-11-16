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

// --- budget, goals and projection (M5-2) ----------------------------------------------------

export interface BudgetLine {
  account_id: string;
  name: string;
  type: MoneyType;
  budgeted: string;
  actual: string;
  remaining: string;
  over: boolean;
}

export interface MonthBudget {
  month: string;
  lines: BudgetLine[];
  budgeted_spending: string;
  actual_spending: string;
}

export type GoalKind = "SAVINGS" | "EMERGENCY_FUND" | "DEBT_PAYOFF";

export interface PersonalGoal {
  id: string;
  kind: GoalKind;
  name: string;
  account_ids: string[];
  target_date: string;
  months: number | null;
  retired_at: string | null;
  current: string;
  target: string;
  months_left: number;
  needed_per_month: string | null;
  pace_per_month: string;
  projected: string;
  status: "ON_TRACK" | "AT_RISK" | "OFF_TRACK";
  average_spending: string | null;
}

export interface Projection {
  as_of: string;
  opening_cash: string;
  months: {
    month: string;
    income: string;
    spending: string;
    closing_cash: string;
    nature: string;
  }[];
  first_negative: string | null;
}

export function useMonthBudget(month: string) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["personal", entityId, "budget", month],
    queryFn: () =>
      api<MonthBudget>(`${base}/personal/budget`, { query: { month } }),
  });
}

export function usePersonalGoals() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["personal", entityId, "goals"],
    queryFn: () => api<PersonalGoal[]>(`${base}/personal/goals`),
  });
}

export function useProjection() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["personal", entityId, "projection"],
    queryFn: () => api<Projection>(`${base}/personal/projection`),
  });
}

export function usePlanMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () =>
    client.invalidateQueries({ queryKey: ["personal", entityId] });
  return {
    budget: useMutation({
      mutationFn: (body: {
        account_id: string;
        monthly_amount: string;
        from_month: string;
      }) =>
        api<MonthBudget>(`${base}/personal/budget`, { method: "PUT", body }),
      onSuccess: refresh,
    }),
    goal: useMutation({
      mutationFn: (body: object) =>
        api<PersonalGoal>(`${base}/personal/goals`, { method: "POST", body }),
      onSuccess: refresh,
    }),
    retire: useMutation({
      mutationFn: (id: string) =>
        api<PersonalGoal>(`${base}/personal/goals/${id}/retire`, {
          method: "POST",
          body: {},
        }),
      onSuccess: refresh,
    }),
  };
}
