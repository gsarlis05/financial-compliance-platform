// Firm portfolio (M4-9).
import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import type { KpiCard } from "./dashboard";
import { useScope } from "./hooks";

export interface PortfolioPart<T> {
  status: "ok" | "empty" | "denied";
  reason: string;
  data: T;
}

export interface PortfolioRow {
  entity_id: string;
  legal_name: string;
  entity_type: string;
  cash: PortfolioPart<{
    as_of?: string;
    stale?: boolean;
    opening?: string;
    first_shortfall?: string | null;
  }>;
  kpis: PortfolioPart<{ cards?: KpiCard[]; stale?: boolean }>;
  goals: PortfolioPart<Record<string, number>>;
  alerts: PortfolioPart<{ warning?: number; critical?: number }>;
}

export function usePortfolio(month: string) {
  const { slug } = useScope();
  return useQuery({
    queryKey: ["portfolio", slug, month],
    queryFn: () =>
      api<PortfolioRow[]>(`/w/${slug}/portfolio`, { query: { month } }),
  });
}
