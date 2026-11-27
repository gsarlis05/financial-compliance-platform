// Tax rules (brief 27, T-2, #255): the VAT codes, the VAT return's box rules and the corporate tax
// rules in force for this company, who has checked them, and corrections from a date, each with
// its source. A correction never edits an earlier one: a later one replaces it from its start.
// Returns and projections prepared earlier keep the rules they used.
import { type SyntheticEvent, useState } from "react";
import { useScope } from "../api/hooks";
import { useTaxRules } from "../api/projections";
import { useReviews } from "../api/reviews";
import {
  type BoxRule,
  useBoxRules,
  useCodesOn,
  useCorrect,
  useCorrections,
} from "../api/taxRules";
import { Page, ProblemMessage } from "../components/common";
import { dayMonthYear } from "../components/ReviewNote";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";

const TREATMENTS = [
  "STANDARD",
  "REDUCED",
  "ZERO",
  "EXEMPT",
  "REVERSE_CHARGE",
  "OUT_OF_SCOPE",
  "SETTLEMENT",
];
const LINES: BoxRule["line"][] = [
  "OUTPUT_VAT",
  "INPUT_VAT",
  "NET_SALE",
  "NET_PURCHASE",
];

const today = () => new Date().toISOString().slice(0, 10);

/** "19" or "19.5" (percent) as "0.19" or "0.195", by moving the decimal point: no floats. */
export function percentToFraction(text: string): string | null {
  const t = text.trim().replace(",", ".");
  if (!/^\d{1,2}(\.\d{1,2})?$/.test(t)) {
    return null;
  }
  const [whole = "0", decimals = ""] = t.split(".");
  const digits = `${whole.padStart(2, "0")}${decimals}`;
  const fraction = `0.${digits}`.replace(/0+$/, "").replace(/\.$/, "");
  return fraction === "0" ? "0" : fraction;
}

/** "0.1900" as "19%". */
function percent(fraction: string | null): string {
  if (fraction === null) {
    return "—";
  }
  const [, decimals = ""] = fraction.split(".");
  const padded = decimals.padEnd(4, "0");
  const whole = String(Number(padded.slice(0, 2)));
  const rest = padded.slice(2).replace(/0+$/, "");
  return `${whole}${rest ? `.${rest}` : ""}%`;
}

function SourceFields({
  source,
  note,
  from,
  onSource,
  onNote,
  onFrom,
  fromLabel,
}: {
  source: string;
  note: string;
  from: string;
  onSource: (v: string) => void;
  onNote: (v: string) => void;
  onFrom: (v: string) => void;
  fromLabel: MessageKey;
}) {
  const { t } = useI18n();
  return (
    <>
      <label>
        {t(fromLabel)}
        <input
          type="date"
          required
          value={from}
          onChange={(e) => onFrom(e.target.value)}
        />
      </label>
      <label>
        {t("tr.source")}
        <input
          required
          maxLength={500}
          value={source}
          onChange={(e) => onSource(e.target.value)}
        />
      </label>
      <label>
        {t("tr.note")}
        <input
          maxLength={1000}
          value={note}
          onChange={(e) => onNote(e.target.value)}
        />
      </label>
    </>
  );
}

function Reviews() {
  const { t } = useI18n();
  const data = useReviews().data;
  if (!Array.isArray(data)) {
    return null;
  }
  return (
    <section className="card stack" aria-labelledby="tr-reviews">
      <h2 id="tr-reviews">{t("tr.reviews")}</h2>
      <ul>
        {data.map((r) => (
          <li key={r.subject}>
            {t(`tr.subject.${r.subject.split(":").pop()}` as MessageKey)}:{" "}
            {r.label}
          </li>
        ))}
      </ul>
    </section>
  );
}

function VatCodes() {
  const { t } = useI18n();
  const [on, setOn] = useState(today);
  const codes = useCodesOn(on);
  const { vatCode } = useCorrect();
  const [code, setCode] = useState("");
  const [from, setFrom] = useState(today);
  const [rate, setRate] = useState("");
  const [treatment, setTreatment] = useState("");
  const [category, setCategory] = useState("");
  const [name, setName] = useState("");
  const [source, setSource] = useState("");
  const [note, setNote] = useState("");
  const [rateError, setRateError] = useState(false);
  const list = codes.data ?? [];
  const categories = [
    ...new Set(list.map((c) => c.category).filter(Boolean)),
  ].sort();
  const submit = (e: SyntheticEvent) => {
    e.preventDefault();
    const fraction = rate ? percentToFraction(rate) : null;
    setRateError(Boolean(rate) && fraction === null);
    if (rate && fraction === null) {
      return;
    }
    vatCode.mutate(
      {
        code,
        effective_from: from,
        ...(fraction !== null ? { rate: fraction } : {}),
        ...(treatment ? { treatment } : {}),
        ...(category ? { category } : {}),
        ...(name ? { name } : {}),
        source,
        note,
      },
      { onSuccess: () => setSource("") },
    );
  };
  return (
    <section className="card stack" aria-labelledby="tr-codes">
      <h2 id="tr-codes">{t("tr.codes")}</h2>
      <label>
        {t("tr.asOn")}
        <input type="date" value={on} onChange={(e) => setOn(e.target.value)} />
      </label>
      <div className="table-scroll">
        <table aria-label={t("tr.codes")}>
          <thead>
            <tr>
              <th scope="col">{t("tr.code")}</th>
              <th scope="col">{t("tr.name")}</th>
              <th scope="col">{t("tr.treatment")}</th>
              <th scope="col">{t("tr.category")}</th>
              <th scope="col" className="num">
                {t("tr.rate")}
              </th>
              <th scope="col">{t("tr.corrected")}</th>
            </tr>
          </thead>
          <tbody>
            {list.map((c) => (
              <tr key={c.id}>
                <td>{c.code}</td>
                <td>{c.name}</td>
                <td>{c.treatment}</td>
                <td>{c.category}</td>
                <td className="num">{percent(c.rate)}</td>
                <td>
                  {c.corrected_from
                    ? `${dayMonthYear(c.corrected_from)} · ${c.correction_source ?? ""}`
                    : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form
        className="stack"
        onSubmit={submit}
        aria-label={t("tr.correctCode")}
      >
        <h3>{t("tr.correctCode")}</h3>
        <label>
          {t("tr.code")}
          <select
            required
            value={code}
            onChange={(e) => setCode(e.target.value)}
          >
            <option value="">{t("tr.choose")}</option>
            {[...new Set(list.map((c) => c.code))].map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("tr.newRate")}
          <input
            inputMode="decimal"
            value={rate}
            aria-invalid={rateError}
            onChange={(e) => setRate(e.target.value)}
          />
        </label>
        {rateError ? <p className="notice warn">{t("tr.rateHelp")}</p> : null}
        <label>
          {t("tr.treatment")}
          <select
            value={treatment}
            onChange={(e) => setTreatment(e.target.value)}
          >
            <option value="">{t("tr.unchanged")}</option>
            {TREATMENTS.map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("tr.category")}
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="">{t("tr.unchanged")}</option>
            {categories.map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("tr.name")}
          <input
            value={name}
            maxLength={200}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <SourceFields
          source={source}
          note={note}
          from={from}
          onSource={setSource}
          onNote={setNote}
          onFrom={setFrom}
          fromLabel="tr.fromLines"
        />
        <button type="submit" className="primary" disabled={vatCode.isPending}>
          {t("tr.save")}
        </button>
        <ProblemMessage error={vatCode.error} />
        {vatCode.isSuccess ? (
          <p className="notice" role="status">
            {t("tr.saved")}
          </p>
        ) : null}
      </form>
    </section>
  );
}

function BoxRules() {
  const { t } = useI18n();
  const [on, setOn] = useState(today);
  const rules = useBoxRules(on);
  const { boxRule } = useCorrect();
  const [category, setCategory] = useState("");
  const [line, setLine] = useState<BoxRule["line"]>("NET_SALE");
  const [status, setStatus] = useState<"MAPPED" | "EXCLUDED">("MAPPED");
  const [boxes, setBoxes] = useState("");
  const [from, setFrom] = useState(today);
  const [source, setSource] = useState("");
  const [note, setNote] = useState("");
  const list = rules.data ?? [];
  const categories = [...new Set(list.map((r) => r.category))];
  const word = (r: BoxRule) =>
    r.status === "MAPPED"
      ? r.boxes.join(", ")
      : t(`tr.status.${r.status}` as MessageKey);
  const submit = (e: SyntheticEvent) => {
    e.preventDefault();
    boxRule.mutate(
      {
        effective_from: from,
        category,
        line,
        status,
        boxes:
          status === "MAPPED"
            ? boxes
                .split(/[,\s]+/)
                .map((b) => b.trim())
                .filter(Boolean)
            : [],
        source,
        note,
      },
      { onSuccess: () => setSource("") },
    );
  };
  return (
    <section className="card stack" aria-labelledby="tr-boxes">
      <h2 id="tr-boxes">{t("tr.boxes")}</h2>
      <label>
        {t("tr.forReturns")}
        <input type="date" value={on} onChange={(e) => setOn(e.target.value)} />
      </label>
      <div className="table-scroll">
        <table aria-label={t("tr.boxes")}>
          <thead>
            <tr>
              <th scope="col">{t("tr.category")}</th>
              {LINES.map((l) => (
                <th scope="col" key={l}>
                  {t(`tr.line.${l}` as MessageKey)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {categories.map((c) => (
              <tr key={c}>
                <th scope="row">{c}</th>
                {LINES.map((l) => {
                  const r = list.find((x) => x.category === c && x.line === l);
                  return (
                    <td key={l} title={r?.reason}>
                      {r ? word(r) : ""}
                      {r?.corrected_from ? " *" : ""}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">{t("tr.boxesHelp")}</p>
      <form className="stack" onSubmit={submit} aria-label={t("tr.correctBox")}>
        <h3>{t("tr.correctBox")}</h3>
        <label>
          {t("tr.category")}
          <select
            required
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="">{t("tr.choose")}</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("tr.lineKind")}
          <select
            value={line}
            onChange={(e) => setLine(e.target.value as BoxRule["line"])}
          >
            {LINES.map((l) => (
              <option key={l} value={l}>
                {t(`tr.line.${l}` as MessageKey)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("tr.goesTo")}
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as "MAPPED" | "EXCLUDED")}
          >
            <option value="MAPPED">{t("tr.status.MAPPED")}</option>
            <option value="EXCLUDED">{t("tr.status.EXCLUDED")}</option>
          </select>
        </label>
        {status === "MAPPED" ? (
          <label>
            {t("tr.boxList")}
            <input
              required
              value={boxes}
              placeholder="6, 1"
              onChange={(e) => setBoxes(e.target.value)}
            />
          </label>
        ) : null}
        <SourceFields
          source={source}
          note={note}
          from={from}
          onSource={setSource}
          onNote={setNote}
          onFrom={setFrom}
          fromLabel="tr.fromReturns"
        />
        <button type="submit" className="primary" disabled={boxRule.isPending}>
          {t("tr.save")}
        </button>
        <ProblemMessage error={boxRule.error} />
        {boxRule.isSuccess ? (
          <p className="notice" role="status">
            {t("tr.saved")}
          </p>
        ) : null}
      </form>
    </section>
  );
}

interface InstalmentRow {
  month: string;
  day: string;
  share: string;
}

function CorporateTax() {
  const { t } = useI18n();
  const rules = useTaxRules();
  const { corporateTax } = useCorrect();
  const year = new Date().getFullYear() + 1;
  const [from, setFrom] = useState(`${year}-01-01`);
  const [rate, setRate] = useState("");
  const [losses, setLosses] = useState("5");
  const [rows, setRows] = useState<InstalmentRow[]>([
    { month: "7", day: "31", share: "50" },
    { month: "12", day: "31", share: "50" },
  ]);
  const [finalAfter, setFinalAfter] = useState("1");
  const [finalMonth, setFinalMonth] = useState("8");
  const [finalDay, setFinalDay] = useState("1");
  const [source, setSource] = useState("");
  const [note, setNote] = useState("");
  const [rateError, setRateError] = useState(false);
  const update = (i: number, key: keyof InstalmentRow, value: string) =>
    setRows(rows.map((r, k) => (k === i ? { ...r, [key]: value } : r)));
  const submit = (e: SyntheticEvent) => {
    e.preventDefault();
    const fraction = percentToFraction(rate);
    const shares = rows.map((r) => percentToFraction(r.share));
    setRateError(fraction === null || shares.some((s) => s === null));
    if (fraction === null || shares.some((s) => s === null)) {
      return;
    }
    corporateTax.mutate(
      {
        effective_from: from,
        rate: fraction,
        loss_carryforward_years: Number(losses),
        tax_year_start_month: Number(from.slice(5, 7)),
        provisional_instalments: rows.map((r, i) => ({
          month: Number(r.month),
          day: Number(r.day),
          share: shares[i],
        })),
        final_payment_years_after: Number(finalAfter),
        final_payment_month: Number(finalMonth),
        final_payment_day: Number(finalDay),
        source,
        note,
      },
      { onSuccess: () => setSource("") },
    );
  };
  return (
    <section className="card stack" aria-labelledby="tr-cit">
      <h2 id="tr-cit">{t("tr.cit")}</h2>
      <div className="table-scroll">
        <table aria-label={t("tr.cit")}>
          <thead>
            <tr>
              <th scope="col">{t("tr.years")}</th>
              <th scope="col" className="num">
                {t("tr.rate")}
              </th>
              <th scope="col">{t("tr.losses")}</th>
              <th scope="col">{t("tr.payments")}</th>
              <th scope="col">{t("tr.status")}</th>
            </tr>
          </thead>
          <tbody>
            {(rules.data ?? []).map((r) => (
              <tr key={r.id}>
                <td>
                  {dayMonthYear(r.effective_from)} –{" "}
                  {r.effective_to ? dayMonthYear(r.effective_to) : ""}
                </td>
                <td className="num">{percent(r.rate)}</td>
                <td>{r.loss_carryforward_years}</td>
                <td>
                  {r.provisional_instalments
                    .map((i) => `${i.day}/${i.month} ${percent(i.share)}`)
                    .join(", ")}
                  {" · "}
                  {r.final_payment}
                </td>
                <td>
                  {r.id.startsWith("CORRECTION:")
                    ? r.verification_note
                    : (r.review_note ?? "")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form className="stack" onSubmit={submit} aria-label={t("tr.correctCit")}>
        <h3>{t("tr.correctCit")}</h3>
        <label>
          {t("tr.rate")} (%)
          <input
            required
            inputMode="decimal"
            value={rate}
            aria-invalid={rateError}
            onChange={(e) => setRate(e.target.value)}
          />
        </label>
        {rateError ? <p className="notice warn">{t("tr.rateHelp")}</p> : null}
        <label>
          {t("tr.losses")}
          <input
            type="number"
            min={0}
            max={50}
            required
            value={losses}
            onChange={(e) => setLosses(e.target.value)}
          />
        </label>
        <fieldset className="stack">
          <legend>{t("tr.instalments")}</legend>
          {rows.map((r, i) => (
            <div className="row" key={i}>
              <label>
                {t("tr.day")}
                <input
                  type="number"
                  min={1}
                  max={31}
                  value={r.day}
                  onChange={(e) => update(i, "day", e.target.value)}
                />
              </label>
              <label>
                {t("tr.month")}
                <input
                  type="number"
                  min={1}
                  max={12}
                  value={r.month}
                  onChange={(e) => update(i, "month", e.target.value)}
                />
              </label>
              <label>
                {t("tr.share")}
                <input
                  inputMode="decimal"
                  value={r.share}
                  onChange={(e) => update(i, "share", e.target.value)}
                />
              </label>
              <button
                type="button"
                onClick={() => setRows(rows.filter((_, k) => k !== i))}
              >
                {t("tr.remove")}
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() =>
              setRows([...rows, { month: "", day: "", share: "" }])
            }
          >
            {t("tr.addInstalment")}
          </button>
        </fieldset>
        <div className="row">
          <label>
            {t("tr.finalAfter")}
            <input
              type="number"
              min={0}
              max={3}
              value={finalAfter}
              onChange={(e) => setFinalAfter(e.target.value)}
            />
          </label>
          <label>
            {t("tr.day")}
            <input
              type="number"
              min={1}
              max={31}
              value={finalDay}
              onChange={(e) => setFinalDay(e.target.value)}
            />
          </label>
          <label>
            {t("tr.month")}
            <input
              type="number"
              min={1}
              max={12}
              value={finalMonth}
              onChange={(e) => setFinalMonth(e.target.value)}
            />
          </label>
        </div>
        <SourceFields
          source={source}
          note={note}
          from={from}
          onSource={setSource}
          onNote={setNote}
          onFrom={setFrom}
          fromLabel="tr.fromYear"
        />
        <button
          type="submit"
          className="primary"
          disabled={corporateTax.isPending}
        >
          {t("tr.save")}
        </button>
        <ProblemMessage error={corporateTax.error} />
        {corporateTax.isSuccess ? (
          <p className="notice" role="status">
            {t("tr.saved")}
          </p>
        ) : null}
      </form>
    </section>
  );
}

function History() {
  const { t } = useI18n();
  const found = useCorrections().data ?? [];
  return (
    <section className="card stack" aria-labelledby="tr-history">
      <h2 id="tr-history">{t("tr.history")}</h2>
      {found.length === 0 ? (
        <p className="muted">{t("tr.none")}</p>
      ) : (
        <div className="table-scroll">
          <table aria-label={t("tr.history")}>
            <thead>
              <tr>
                <th scope="col">{t("tr.from")}</th>
                <th scope="col">{t("tr.what")}</th>
                <th scope="col">{t("tr.change")}</th>
                <th scope="col">{t("tr.source")}</th>
                <th scope="col">{t("tr.by")}</th>
              </tr>
            </thead>
            <tbody>
              {found.map((c) => (
                <tr key={c.id}>
                  <td>{dayMonthYear(c.effective_from)}</td>
                  <td>
                    {t(`tr.kind.${c.kind}` as MessageKey)} {c.target}
                  </td>
                  <td>{JSON.stringify(c.values)}</td>
                  <td>{c.source}</td>
                  <td>
                    {c.created_by} · {dayMonthYear(c.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function TaxRulesPage() {
  const { t } = useI18n();
  useScope();
  return (
    <Page title={t("tr.title")}>
      <p className="muted">{t("tr.help")}</p>
      <Reviews />
      <VatCodes />
      <BoxRules />
      <CorporateTax />
      <History />
    </Page>
  );
}
