// Ledger settings of an entity: when a second person must approve an entry, foreign currency
// (V1-2h: switched on with the account exchange differences go to) and the exchange rates.
import { type SyntheticEvent, useState } from "react";
import { useAccounts } from "../api/hooks";
import {
  CURRENCIES,
  type CurrencySettings,
  type LedgerSettings,
  useCurrencySettings,
  useExchangeRates,
  useLedgerSettings,
} from "../api/currency";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";

function Approvals() {
  const { get } = useLedgerSettings();
  if (!get.data) {
    return get.isPending ? <Loading /> : <ProblemMessage error={get.error} />;
  }
  return <ApprovalsForm initial={get.data} />;
}

function ApprovalsForm({ initial }: { initial: LedgerSettings }) {
  const { t } = useI18n();
  const { save } = useLedgerSettings();
  const [policy, setPolicy] = useState(initial.approval_policy);
  const [threshold, setThreshold] = useState(initial.approval_threshold ?? "");
  function submit(event: SyntheticEvent) {
    event.preventDefault();
    save.mutate({
      approval_policy: policy,
      approval_threshold:
        policy === "THRESHOLD" ? threshold.replace(",", ".") : null,
    });
  }
  return (
    <form
      className="panel form"
      onSubmit={submit}
      aria-labelledby="ls-approvals"
    >
      <h2 id="ls-approvals">{t("ls.approvals")}</h2>
      <p className="muted">{t("ls.approvalsHelp")}</p>
      <label>
        {t("ls.policy")}
        <select
          value={policy}
          onChange={(e) =>
            setPolicy(e.target.value as LedgerSettings["approval_policy"])
          }
        >
          {(["NONE", "THRESHOLD", "ALWAYS"] as const).map((p) => (
            <option key={p} value={p}>
              {t(`ls.policy.${p}` as MessageKey)}
            </option>
          ))}
        </select>
      </label>
      {policy === "THRESHOLD" ? (
        <label>
          {t("ls.threshold")}
          <input
            inputMode="decimal"
            required
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
          />
        </label>
      ) : null}
      <button type="submit" disabled={save.isPending}>
        {t("ls.save")}
      </button>
      {save.isSuccess ? <p role="status">{t("ls.saved")}</p> : null}
      <ProblemMessage error={save.error} />
    </form>
  );
}

function ForeignCurrency() {
  const { get } = useCurrencySettings();
  if (!get.data) {
    return get.isPending ? <Loading /> : <ProblemMessage error={get.error} />;
  }
  return <ForeignCurrencyForm initial={get.data} />;
}

function ForeignCurrencyForm({ initial }: { initial: CurrencySettings }) {
  const { t, locale } = useI18n();
  const { save } = useCurrencySettings();
  const accounts = useAccounts();
  const [enabled, setEnabled] = useState(initial.multi_currency_enabled);
  const [account, setAccount] = useState(initial.fx_account_id ?? "");
  const choices = (accounts.data ?? []).filter(
    (a) =>
      a.is_postable &&
      a.status === "ACTIVE" &&
      (a.type === "INCOME" || a.type === "EXPENSE"),
  );
  function submit(event: SyntheticEvent) {
    event.preventDefault();
    save.mutate({
      multi_currency_enabled: enabled,
      fx_account_id: account || null,
    });
  }
  return (
    <form className="panel form" onSubmit={submit} aria-labelledby="ls-fx">
      <h2 id="ls-fx">{t("ls.fx")}</h2>
      <p className="muted">
        {t("ls.fxHelp").replace("{currency}", initial.functional_currency)}
      </p>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
        />
        {t("ls.fxOn")}
      </label>
      <label>
        {t("ls.fxAccount")}
        <select value={account} onChange={(e) => setAccount(e.target.value)}>
          <option value="">—</option>
          {choices.map((a) => (
            <option key={a.id} value={a.id}>
              {a.code} · {locale === "el" && a.name_el ? a.name_el : a.name}
            </option>
          ))}
        </select>
      </label>
      <button type="submit" disabled={save.isPending}>
        {t("ls.save")}
      </button>
      {save.isSuccess ? <p role="status">{t("ls.saved")}</p> : null}
      <ProblemMessage error={save.error} />
    </form>
  );
}

function Rates() {
  const { t } = useI18n();
  const { list, add } = useExchangeRates();
  const [form, setForm] = useState({
    rate_date: "",
    base_currency: "EUR",
    quote_currency: "USD",
    rate: "",
    rate_type: "SPOT",
    source: "",
  });
  function submit(event: SyntheticEvent) {
    event.preventDefault();
    add.mutate(
      { ...form, rate: form.rate.trim().replace(",", ".") },
      { onSuccess: () => setForm({ ...form, rate: "" }) },
    );
  }
  const currencies = Object.keys(CURRENCIES);
  return (
    <section className="panel" aria-labelledby="ls-rates">
      <h2 id="ls-rates">{t("ls.rates")}</h2>
      <p className="muted">{t("ls.ratesHelp")}</p>
      {list.data?.length ? (
        <div className="table-scroll">
          <table aria-label={t("ls.rates")}>
            <thead>
              <tr>
                <th scope="col">{t("ls.rateDate")}</th>
                <th scope="col">{t("ls.pair")}</th>
                <th scope="col" className="amount">
                  {t("ls.rate")}
                </th>
                <th scope="col">{t("ls.rateType")}</th>
                <th scope="col">{t("ls.source")}</th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((r) => (
                <tr key={r.id}>
                  <td>{r.rate_date}</td>
                  <td>
                    1 {r.base_currency} = … {r.quote_currency}
                  </td>
                  <td className="amount">{r.rate}</td>
                  <td>{t(`ls.rateType.${r.rate_type}` as MessageKey)}</td>
                  <td>{r.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">{t("ls.noRates")}</p>
      )}
      <form className="form inline" onSubmit={submit}>
        <label>
          {t("ls.rateDate")}
          <input
            type="date"
            required
            value={form.rate_date}
            onChange={(e) => setForm({ ...form, rate_date: e.target.value })}
          />
        </label>
        <label>
          {t("ls.base")}
          <select
            value={form.base_currency}
            onChange={(e) =>
              setForm({ ...form, base_currency: e.target.value })
            }
          >
            {currencies.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>
          {t("ls.quote")}
          <select
            value={form.quote_currency}
            onChange={(e) =>
              setForm({ ...form, quote_currency: e.target.value })
            }
          >
            {currencies.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>
          {t("ls.rate")}
          <input
            inputMode="decimal"
            required
            value={form.rate}
            onChange={(e) => setForm({ ...form, rate: e.target.value })}
          />
        </label>
        <label>
          {t("ls.rateType")}
          <select
            value={form.rate_type}
            onChange={(e) => setForm({ ...form, rate_type: e.target.value })}
          >
            {(["SPOT", "CLOSING", "AVERAGE"] as const).map((k) => (
              <option key={k} value={k}>
                {t(`ls.rateType.${k}` as MessageKey)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("ls.source")}
          <input
            required
            maxLength={200}
            value={form.source}
            onChange={(e) => setForm({ ...form, source: e.target.value })}
          />
        </label>
        <button type="submit" disabled={add.isPending}>
          {t("ls.addRate")}
        </button>
      </form>
      <ProblemMessage error={add.error} />
    </section>
  );
}

export function LedgerSettingsPage() {
  const { t } = useI18n();
  return (
    <Page title={t("ls.title")}>
      <Approvals />
      <ForeignCurrency />
      <Rates />
    </Page>
  );
}
