// Decimal arithmetic for previews in the UI (ADR-0003). The server is authoritative; the UI only
// adds amounts to show live totals. JavaScript numbers are never used for money.
import Decimal from "decimal.js";

const AMOUNT = /^\d{1,15}(\.\d{1,4})?$/;

export function isAmount(value: string): boolean {
  return value === "" || AMOUNT.test(value.trim());
}

export function toDecimal(value: string): Decimal {
  const trimmed = value.trim();
  return trimmed === "" || !AMOUNT.test(trimmed) ? new Decimal(0) : new Decimal(trimmed);
}

export function sum(values: readonly string[]): Decimal {
  return values.reduce((acc, v) => acc.plus(toDecimal(v)), new Decimal(0));
}

export function formatAmount(value: string | Decimal, locale = "en"): string {
  const decimal = typeof value === "string" ? toDecimal(value) : value;
  const [whole = "0", fraction = "00"] = decimal.toFixed(2).split(".");
  const negative = whole.startsWith("-");
  const digits = negative ? whole.slice(1) : whole;
  const group = locale === "el" ? "." : ",";
  const separator = locale === "el" ? "," : ".";
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, group);
  return `${negative ? "-" : ""}${grouped}${separator}${fraction}`;
}

export function normaliseAmount(value: string): string {
  const trimmed = value.trim();
  return trimmed === "" ? "0" : trimmed;
}
