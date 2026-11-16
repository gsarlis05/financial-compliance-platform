// Working capital (M7-7 for M7-4): receivables, stock and payables by month, the days that drive
// them and the cash conversion cycle, next to the days seen over the last 12 months; and what N
// days are worth, worked out by running the projection again.
import { type SyntheticEvent, useState } from "react";
import { useDaysWorth, useWorkingCapital } from "../api/scenarios";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";
import { BasePicker, baseOf } from "./Sensitivity";

export function WorkingCapitalPage() {
  const { t, locale } = useI18n();
  const [choice, setChoice] = useState("");
  const wc = useWorkingCapital(choice ? baseOf(choice) : null);
  const worth = useDaysWorth();
  const [driver, setDriver] = useState<"dso" | "dio" | "dpo">("dso");
  const [days, setDays] = useState("-10");
  const v = wc.data;
  const amount = (x: string) => formatAmount(x, locale);
  const submit = (e: SyntheticEvent) => {
    e.preventDefault();
    worth.mutate({ ...baseOf(choice), driver, days: Number(days) });
  };
  return (
    <Page title={t("nav.workingCapital")}>
      <p>{t("wc.intro")}</p>
      <p className="notice" role="note">
        {t("pj.pendingReview")}
      </p>
      <div className="form inline">
        <BasePicker value={choice} onChange={setChoice} />
      </div>
      {wc.isLoading ? <Loading /> : null}
      {wc.error ? <ProblemMessage error={wc.error} /> : null}
      {v ? (
        <>
          <p role="status">
            {v.base_label} · {t(`nature.${v.nature}` as MessageKey)}
          </p>
          <p>
            {t("wc.observed")}: DSO {v.observed.dso}, DIO {v.observed.dio}, DPO{" "}
            {v.observed.dpo} · {t("wc.ccc")} {v.observed_ccc}
          </p>
          <div className="table-scroll">
            <table>
              <caption>{t("wc.caption")}</caption>
              <thead>
                <tr>
                  {[
                    "month",
                    "receivables",
                    "inventory",
                    "payables",
                    "net",
                    "change",
                    "cashEffect",
                    "dso",
                    "dio",
                    "dpo",
                    "ccc",
                  ].map((k) => (
                    <th scope="col" key={k}>
                      {t(`wc.c.${k}` as MessageKey)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {v.months.map((m) => (
                  <tr key={m.month}>
                    <th scope="row">{m.month.slice(0, 7)}</th>
                    <td className="amount">{amount(m.receivables)}</td>
                    <td className="amount">{amount(m.inventory)}</td>
                    <td className="amount">{amount(m.payables)}</td>
                    <td className="amount">{amount(m.net)}</td>
                    <td className="amount">{amount(m.change)}</td>
                    <td className="amount">{amount(m.cash_effect)}</td>
                    <td>{m.dso}</td>
                    <td>{m.dio}</td>
                    <td>{m.dpo}</td>
                    <td>{m.ccc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <form
            className="form inline"
            onSubmit={submit}
            aria-labelledby="wc-worth"
          >
            <h2 id="wc-worth">{t("wc.worth")}</h2>
            <label>
              {t("se.driver")}
              <select
                value={driver}
                onChange={(e) =>
                  setDriver(e.target.value as "dso" | "dio" | "dpo")
                }
              >
                <option value="dso">{t("se.d.dso")}</option>
                <option value="dio">{t("se.d.dio")}</option>
                <option value="dpo">{t("se.d.dpo")}</option>
              </select>
            </label>
            <label>
              {t("se.days")}
              <input
                inputMode="numeric"
                value={days}
                onChange={(e) => setDays(e.target.value)}
              />
            </label>
            <button type="submit" disabled={worth.isPending}>
              {t("wc.workOut")}
            </button>
          </form>
          {worth.error ? <ProblemMessage error={worth.error} /> : null}
          {worth.data ? (
            <p role="status">
              {t("wc.result")
                .replace("{closing}", amount(worth.data.closing_cash_change))
                .replace("{lowest}", amount(worth.data.lowest_cash_change))
                .replace(
                  "{nwc}",
                  amount(worth.data.net_working_capital_change),
                )}{" "}
              ({t("nature.HYPOTHETICAL")})
            </p>
          ) : null}
        </>
      ) : null}
    </Page>
  );
}
