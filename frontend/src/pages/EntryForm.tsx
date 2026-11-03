import { type FormEvent, useState } from "react";
import type { Account, EntryInput, FiscalYear, JournalEntry, Period } from "../api/types";
import { FieldError, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import { formatAmount, isAmount, normaliseAmount, sum } from "../money";

interface LineState {
  key: number;
  account_id: string;
  debit: string;
  credit: string;
  memo: string;
}

let nextKey = 1;
const emptyLine = (): LineState => ({ key: nextKey++, account_id: "", debit: "", credit: "", memo: "" });

export function periodFor(years: FiscalYear[], date: string, adjustment: boolean): Period | undefined {
  for (const year of years) {
    const found = year.periods.find(
      (p) => p.is_adjustment === adjustment && p.start_date <= date && date <= p.end_date,
    );
    if (found) {
      return found;
    }
  }
  return undefined;
}

interface Props {
  accounts: Account[];
  fiscalYears: FiscalYear[];
  initial?: JournalEntry | undefined;
  saving: boolean;
  error: unknown;
  onSave: (body: EntryInput, submit: boolean) => void;
}

export function EntryForm({ accounts, fiscalYears, initial, saving, error, onSave }: Props) {
  const { t, locale } = useI18n();
  const [date, setDate] = useState(initial?.accounting_date ?? new Date().toISOString().slice(0, 10));
  const [description, setDescription] = useState(initial?.description ?? "");
  const [adjustment, setAdjustment] = useState(initial?.use_adjustment_period ?? false);
  const [lines, setLines] = useState<LineState[]>(
    initial?.lines.map((l) => ({
      key: nextKey++,
      account_id: l.account_id,
      debit: l.debit === "0.00" ? "" : l.debit,
      credit: l.credit === "0.00" ? "" : l.credit,
      memo: l.memo,
    })) ?? [emptyLine(), emptyLine()],
  );

  const postable = accounts.filter((a) => a.is_postable && a.status === "ACTIVE");
  const totalDebit = sum(lines.map((l) => l.debit));
  const totalCredit = sum(lines.map((l) => l.credit));
  const difference = totalDebit.minus(totalCredit).abs();
  const amountsValid = lines.every((l) => isAmount(l.debit) && isAmount(l.credit));
  const balanced = difference.isZero() && !totalDebit.isZero();
  const period = periodFor(fiscalYears, date, adjustment);

  const update = (key: number, change: Partial<LineState>) =>
    setLines(lines.map((l) => (l.key === key ? { ...l, ...change } : l)));

  function body(): EntryInput {
    return {
      accounting_date: date,
      description,
      use_adjustment_period: adjustment,
      lines: lines.map((l) => ({
        account_id: l.account_id,
        debit: normaliseAmount(l.debit),
        credit: normaliseAmount(l.credit),
        memo: l.memo,
      })),
    };
  }

  function handle(event: FormEvent, submit: boolean) {
    event.preventDefault();
    onSave(body(), submit);
  }

  return (
    <form className="entry-form" onSubmit={(e) => handle(e, true)} aria-describedby="entry-balance">
      <div className="form inline">
        <label>
          {t("je.date")}
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          <FieldError error={error} field="accounting_date" />
        </label>
        <label className="grow">
          {t("je.description")}
          <input value={description} onChange={(e) => setDescription(e.target.value)} required maxLength={500} />
          <FieldError error={error} field="description" />
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={adjustment} onChange={(e) => setAdjustment(e.target.checked)} />
          {t("je.adjustmentPeriod")}
        </label>
      </div>
      {period?.status === "LOCKED" ? <p className="notice warn">{t("per.lockedHelp")}</p> : null}
      {period?.status === "SOFT_CLOSED" ? <p className="notice">{t("per.softClosedHelp")}</p> : null}
      <table className="lines">
        <thead>
          <tr>
            <th scope="col">{t("je.account")}</th>
            <th scope="col">{t("je.debit")}</th>
            <th scope="col">{t("je.credit")}</th>
            <th scope="col">{t("je.memo")}</th>
            <th scope="col">
              <span className="visually-hidden">{t("je.removeLine")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line, index) => (
            <tr key={line.key}>
              <td>
                <select
                  aria-label={`${t("je.account")} ${index + 1}`}
                  value={line.account_id}
                  onChange={(e) => update(line.key, { account_id: e.target.value })}
                  required
                >
                  <option value="">—</option>
                  {postable.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.code} · {locale === "el" && a.name_el ? a.name_el : a.name}
                    </option>
                  ))}
                </select>
                <FieldError error={error} field={`lines.${index}.account_id`} />
              </td>
              <td>
                <input
                  aria-label={`${t("je.debit")} ${index + 1}`}
                  inputMode="decimal"
                  className="amount"
                  value={line.debit}
                  aria-invalid={!isAmount(line.debit)}
                  onChange={(e) => update(line.key, { debit: e.target.value })}
                />
                <FieldError error={error} field={`lines.${index}.debit`} />
              </td>
              <td>
                <input
                  aria-label={`${t("je.credit")} ${index + 1}`}
                  inputMode="decimal"
                  className="amount"
                  value={line.credit}
                  aria-invalid={!isAmount(line.credit)}
                  onChange={(e) => update(line.key, { credit: e.target.value })}
                />
                <FieldError error={error} field={`lines.${index}.credit`} />
                <FieldError error={error} field={`lines.${index}`} />
              </td>
              <td>
                <input
                  aria-label={`${t("je.memo")} ${index + 1}`}
                  value={line.memo}
                  maxLength={300}
                  onChange={(e) => update(line.key, { memo: e.target.value })}
                />
              </td>
              <td>
                <button
                  type="button"
                  className="link-button"
                  aria-label={`${t("je.removeLine")} ${index + 1}`}
                  disabled={lines.length <= 2}
                  onClick={() => setLines(lines.filter((l) => l.key !== line.key))}
                >
                  ×
                </button>
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">{t("je.totals")}</th>
            <td className="amount" data-testid="total-debit">
              {formatAmount(totalDebit, locale)}
            </td>
            <td className="amount" data-testid="total-credit">
              {formatAmount(totalCredit, locale)}
            </td>
            <td colSpan={2} id="entry-balance" aria-live="polite" className={balanced ? "ok" : "warn"}>
              {balanced ? t("je.balanced") : `${t("je.difference")}: ${formatAmount(difference, locale)}`}
            </td>
          </tr>
        </tfoot>
      </table>
      <button type="button" className="link-button" onClick={() => setLines([...lines, emptyLine()])}>
        + {t("je.addLine")}
      </button>
      {!balanced ? <p className="notice">{t("je.unbalanced")}</p> : null}
      <ProblemMessage error={error} />
      <div className="actions">
        <button type="button" disabled={saving || !amountsValid} onClick={(e) => handle(e, false)}>
          {t("je.saveDraft")}
        </button>
        <button type="submit" className="primary" disabled={saving || !amountsValid || !balanced}>
          {t("je.saveAndSubmit")}
        </button>
      </div>
    </form>
  );
}
