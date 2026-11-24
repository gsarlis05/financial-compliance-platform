// Ledger settings (approval policy), foreign currency (V1-2h: switched on per entity with the
// account exchange differences go to) and exchange rates as sourced data.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./client";
import { useScope } from "./hooks";

export interface LedgerSettings {
  approval_policy: "NONE" | "THRESHOLD" | "ALWAYS";
  approval_threshold: string | null;
}

export interface CurrencySettings {
  functional_currency: string;
  multi_currency_enabled: boolean;
  fx_account_id: string | null;
}

export interface ExchangeRate {
  id: string;
  rate_date: string;
  base_currency: string;
  quote_currency: string;
  rate: string;
  rate_type: "SPOT" | "CLOSING" | "AVERAGE";
  source: string;
  source_hash: string;
  created_at: string;
}

export interface SuggestedRate {
  currency: string;
  rate: string;
  rate_date: string;
  rate_type: string;
  source: string;
}

/** The ISO 4217 currencies the platform knows (core_currency) and their decimals. */
export const CURRENCIES: Record<string, number> = {
  EUR: 2,
  USD: 2,
  GBP: 2,
  CHF: 2,
  SEK: 2,
  NOK: 2,
  DKK: 2,
  PLN: 2,
  CZK: 2,
  HUF: 2,
  RON: 2,
  BGN: 2,
  ILS: 2,
  AED: 2,
  RUB: 2,
  CNY: 2,
  JPY: 0,
  KWD: 3,
  BHD: 3,
};

export function useLedgerSettings() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const key = ["ledger-settings", entityId];
  const get = useQuery({
    queryKey: key,
    queryFn: () => api<LedgerSettings>(`${base}/ledger-settings`),
  });
  const save = useMutation({
    mutationFn: (body: LedgerSettings) =>
      api<LedgerSettings>(`${base}/ledger-settings`, { method: "PUT", body }),
    onSuccess: (data) => client.setQueryData(key, data),
  });
  return { get, save };
}

export function useCurrencySettings() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const key = ["currency-settings", entityId];
  const get = useQuery({
    queryKey: key,
    queryFn: () => api<CurrencySettings>(`${base}/currency-settings`),
  });
  const save = useMutation({
    mutationFn: (body: {
      multi_currency_enabled: boolean;
      fx_account_id: string | null;
    }) =>
      api<CurrencySettings>(`${base}/currency-settings`, {
        method: "PUT",
        body,
      }),
    onSuccess: (data) => client.setQueryData(key, data),
  });
  return { get, save };
}

export function useExchangeRates() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const key = ["exchange-rates", entityId];
  const list = useQuery({
    queryKey: key,
    queryFn: () => api<ExchangeRate[]>(`${base}/exchange-rates`),
  });
  const add = useMutation({
    mutationFn: (body: {
      rate_date: string;
      base_currency: string;
      quote_currency: string;
      rate: string;
      rate_type: string;
      source: string;
    }) => api<ExchangeRate>(`${base}/exchange-rates`, { method: "POST", body }),
    onSuccess: () => client.invalidateQueries({ queryKey: key }),
  });
  return { list, add };
}

/** The stored rate to suggest for a currency on a date, or null when none is stored. */
export function useSuggestRate() {
  const { base } = useScope();
  return async (
    currency: string,
    on: string,
  ): Promise<SuggestedRate | null> => {
    try {
      return await api<SuggestedRate>(`${base}/exchange-rates/suggestion`, {
        query: { currency, on },
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        return null;
      }
      throw error;
    }
  };
}

/** A foreign-currency position and its exchange difference (V1-2h2, #230). */
export interface FxPosition {
  account_id: string;
  account_code: string;
  account_name: string;
  counterparty_id: string | null;
  currency: string;
  foreign: string;
  euros: string;
  rate: string | null;
  rate_date: string | null;
  rate_source: string;
  revalued: string | null;
  difference: string;
  kind: "UNREALISED" | "REALISED" | "NO_RATE" | "";
}

export interface FxPositions {
  on: string;
  positions: FxPosition[];
  unrealised: string;
  realised: string;
  missing_rates: string[];
  fx_account_id: string | null;
  waiting_entry_id: string | null;
}

export function useFxPositions(on: string) {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const key = ["fx-positions", entityId, on];
  const list = useQuery({
    queryKey: key,
    queryFn: () => api<FxPositions>(`${base}/fx-positions`, { query: { on } }),
    enabled: !!on,
  });
  const prepare = useMutation({
    mutationFn: () =>
      api<{ id: string }>(`${base}/fx-differences`, {
        method: "POST",
        body: { on },
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: key }),
  });
  return { list, prepare };
}
