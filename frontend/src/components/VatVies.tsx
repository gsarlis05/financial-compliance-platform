// VIES statements for a VAT period (V1-2g): recorded as the owner filed them (nothing is sent),
// and reconciled to the EU supplies in the books and to Boxes 8A and 8B.
import { type SyntheticEvent, useState } from "react";
import { type VatReportDetail, type VatViesLine, useVatVies } from "../api/vat";
import { ProblemMessage } from "./common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

const EMPTY: VatViesLine = {
  country: "",
  vat_no: "",
  goods: "",
  services: "",
  triangular: "",
};

export function VatVies({ report }: { report: VatReportDetail }) {
  const { t, locale } = useI18n();
  const v = report.vies;
  const { list, record, voidStatement } = useVatVies(
    report.period_start,
    report.period_end,
  );
  const [month, setMonth] = useState(v.months[0]?.month ?? "");
  const [kind, setKind] = useState<"ORIGINAL" | "CORRECTION">("ORIGINAL");
  const [filedOn, setFiledOn] = useState("");
  const [reference, setReference] = useState("");
  const [lines, setLines] = useState<VatViesLine[]>([{ ...EMPTY }]);
  const [reason, setReason] = useState("");
  const money = (x: string) => formatAmount(x, locale);
  const relevant =
    v.partners.length > 0 ||
    (list.data?.length ?? 0) > 0 ||
    v.months.some((m) => m.supplies);
  if (!relevant) {
    return null;
  }
  const decimal = (x: string) => x.trim().replace(",", ".") || "0";
  const update = (i: number, change: Partial<VatViesLine>) =>
    setLines(lines.map((l, j) => (j === i ? { ...l, ...change } : l)));
  function save(event: SyntheticEvent) {
    event.preventDefault();
    record.mutate(
      {
        month,
        kind,
        filed_on: filedOn,
        reference,
        lines: lines.map((l) => ({
          country: l.country.trim().toUpperCase(),
          vat_no: l.vat_no,
          goods: decimal(l.goods),
          services: decimal(l.services),
          triangular: decimal(l.triangular),
        })),
      },
      {
        onSuccess: () => {
          setReference("");
          setLines([{ ...EMPTY }]);
        },
      },
    );
  }
  return (
    <section aria-labelledby="vat-vies">
      <h3 id="vat-vies">{t("vat.vies.title")}</h3>
      <p className="muted">{t("vat.vies.help")}</p>
      {v.missing_months.length ? (
        <p className="notice warn">
          {t("vat.vies.missing")}{" "}
          {v.missing_months.map((m) => m.slice(0, 7)).join(", ")}
        </p>
      ) : null}
      <div className="table-scroll">
        <table aria-label={t("vat.vies.partners")}>
          <thead>
            <tr>
              <th scope="col">{t("vat.country")}</th>
              <th scope="col">{t("vat.vatNo")}</th>
              <th scope="col" className="amount">
                {t("vat.vies.booksGoods")}
              </th>
              <th scope="col" className="amount">
                {t("vat.vies.viesGoods")}
              </th>
              <th scope="col" className="amount">
                {t("vat.vies.booksServices")}
              </th>
              <th scope="col" className="amount">
                {t("vat.vies.viesServices")}
              </th>
              <th scope="col" className="amount">
                {t("vat.vies.triangular")}
              </th>
              <th scope="col">{t("vat.vies.status")}</th>
            </tr>
          </thead>
          <tbody>
            {v.partners.map((p) => (
              <tr key={`${p.country}${p.vat_no}`}>
                <td>{p.country}</td>
                <td>{p.vat_no}</td>
                <td className="amount">{money(p.books_goods)}</td>
                <td className="amount">{money(p.vies_goods)}</td>
                <td className="amount">{money(p.books_services)}</td>
                <td className="amount">{money(p.vies_services)}</td>
                <td className="amount">{money(p.vies_triangular)}</td>
                <td>{t(`vat.vies.status.${p.status}` as MessageKey)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul>
        {v.totals.map((x) => (
          <li key={x.box}>
            {t("vat.box")} {x.box}: {money(x.box_exact)} · VIES {money(x.vies)}{" "}
            · {t("vat.vies.difference")} {money(x.difference)}
          </li>
        ))}
        <li>
          {t("vat.vies.triangularTotal")} {money(v.triangular)}
        </li>
      </ul>
      <p role="status">
        {v.agrees ? t("vat.vies.agrees") : t("vat.vies.differs")}
      </p>
      {list.data?.length ? (
        <ul>
          {list.data.map((s) => (
            <li key={s.id} className={s.voided ? "muted" : undefined}>
              {s.month.slice(0, 7)} ·{" "}
              {t(`vat.vies.kind.${s.kind}` as MessageKey)} · {s.filed_on} ·{" "}
              {s.reference} · {s.lines.length} {t("vat.vies.partnersCount")}
              {s.voided ? ` · ${t("vat.imp.voided")}: ${s.void_reason}` : ""}
              {!s.voided ? (
                <>
                  {" "}
                  <input
                    aria-label={`${t("vat.imp.voidReason")} ${s.reference}`}
                    placeholder={t("vat.imp.voidReason")}
                    value={reason}
                    maxLength={500}
                    onChange={(e) => setReason(e.target.value)}
                  />
                  <button
                    type="button"
                    className="link-button"
                    disabled={!reason.trim() || voidStatement.isPending}
                    onClick={() => voidStatement.mutate({ id: s.id, reason })}
                  >
                    {t("vat.imp.void")}
                  </button>
                </>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      <form className="form" onSubmit={save} aria-label={t("vat.vies.record")}>
        <div className="form inline">
          <label>
            {t("vat.vies.month")}
            <select value={month} onChange={(e) => setMonth(e.target.value)}>
              {v.months.map((m) => (
                <option key={m.month} value={m.month}>
                  {m.month.slice(0, 7)}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("vat.vies.kind")}
            <select
              value={kind}
              onChange={(e) =>
                setKind(e.target.value as "ORIGINAL" | "CORRECTION")
              }
            >
              <option value="ORIGINAL">{t("vat.vies.kind.ORIGINAL")}</option>
              <option value="CORRECTION">
                {t("vat.vies.kind.CORRECTION")}
              </option>
            </select>
          </label>
          <label>
            {t("vat.vies.filedOn")}
            <input
              type="date"
              required
              value={filedOn}
              onChange={(e) => setFiledOn(e.target.value)}
            />
          </label>
          <label>
            {t("vat.reference")}
            <input
              required
              maxLength={100}
              value={reference}
              onChange={(e) => setReference(e.target.value)}
            />
          </label>
        </div>
        {lines.map((l, i) => (
          <div className="form inline" key={i}>
            <label>
              {t("vat.country")} {i + 1}
              <input
                required
                maxLength={2}
                value={l.country}
                onChange={(e) =>
                  update(i, { country: e.target.value.toUpperCase() })
                }
              />
            </label>
            <label>
              {t("vat.vatNo")} {i + 1}
              <input
                required
                maxLength={30}
                value={l.vat_no}
                onChange={(e) => update(i, { vat_no: e.target.value })}
              />
            </label>
            <label>
              {t("vat.vies.goods")} {i + 1}
              <input
                inputMode="decimal"
                value={l.goods}
                onChange={(e) => update(i, { goods: e.target.value })}
              />
            </label>
            <label>
              {t("vat.vies.services")} {i + 1}
              <input
                inputMode="decimal"
                value={l.services}
                onChange={(e) => update(i, { services: e.target.value })}
              />
            </label>
            <label>
              {t("vat.vies.triangular")} {i + 1}
              <input
                inputMode="decimal"
                value={l.triangular}
                onChange={(e) => update(i, { triangular: e.target.value })}
              />
            </label>
          </div>
        ))}
        <div className="actions">
          <button
            type="button"
            className="link-button"
            onClick={() => setLines([...lines, { ...EMPTY }])}
          >
            + {t("vat.vies.addPartner")}
          </button>
          <button type="submit" disabled={record.isPending}>
            {t("vat.vies.record")}
          </button>
        </div>
      </form>
      <ProblemMessage error={record.error ?? voidStatement.error} />
    </section>
  );
}
