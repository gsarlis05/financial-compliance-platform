// A bank's CSV export recognised from the file (R-1, #244): the columns found, any question the
// file leaves open, and a preview, before the layout is saved and the file imported.
import { useEffect, useState } from "react";
import {
  type CsvDetection,
  type CsvMapping,
  useBankPresets,
  useCsvLayout,
} from "../api/bankCsv";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";
import { ProblemMessage } from "./common";

const FORMAT_LABEL: Record<string, string> = {
  "%d/%m/%Y": "31/12/2026",
  "%m/%d/%Y": "12/31/2026",
  "%d/%m/%y": "31/12/26",
};

function answer(mapping: CsvMapping, field: string, value: string): CsvMapping {
  return field === "decimal_comma"
    ? { ...mapping, decimal_comma: value === "comma" }
    : { ...mapping, date_format: value };
}

export function CsvLayout({
  accountId,
  file,
  importing,
  onImport,
}: {
  accountId: string;
  file: File;
  importing: boolean;
  onImport: () => void;
}) {
  const { t, locale } = useI18n();
  const presets = useBankPresets();
  const { detect, save } = useCsvLayout(accountId);
  const [preset, setPreset] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const { mutate } = detect;
  useEffect(() => {
    mutate({ file, preset });
  }, [file, preset, mutate]);
  const found: CsvDetection | undefined = detect.data;
  const chosen = (field: string, fallback: string) =>
    answers[field] ?? fallback;
  const mapping = found
    ? found.questions.reduce(
        (m, q) => answer(m, q.field, chosen(q.field, q.chosen)),
        found.mapping,
      )
    : null;

  return (
    <section className="panel" aria-labelledby="csv-layout">
      <h3 id="csv-layout">{t("csv.title")}</h3>
      <label>
        {t("csv.bank")}
        <select value={preset} onChange={(e) => setPreset(e.target.value)}>
          <option value="">{t("csv.anyBank")}</option>
          {presets.data?.map((p) => (
            <option key={p.key} value={p.key}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      {found?.preset ? <p className="muted">{t("csv.toConfirm")}</p> : null}
      <ProblemMessage error={detect.error} />
      {found && mapping ? (
        <>
          <p className="muted">
            {t("csv.found")}{" "}
            {Object.entries(found.columns)
              .map(([f, c]) => `${t(`csv.f.${f}` as MessageKey)}: “${c}”`)
              .join(" · ")}
          </p>
          {found.questions.map((q) => (
            <label key={q.field}>
              {t(`csv.q.${q.field}` as MessageKey)}
              <select
                value={chosen(q.field, q.chosen)}
                onChange={(e) =>
                  setAnswers({ ...answers, [q.field]: e.target.value })
                }
              >
                {q.options.map((o) => (
                  <option key={o} value={o}>
                    {q.field === "decimal_comma"
                      ? t(`csv.sep.${o}` as MessageKey)
                      : (FORMAT_LABEL[o] ?? o)}
                  </option>
                ))}
              </select>
            </label>
          ))}
          {found.error ? (
            <p className="notice warn" role="status">
              {found.error}
            </p>
          ) : (
            <div className="table-scroll">
              <table aria-label={t("csv.preview")}>
                <thead>
                  <tr>
                    <th scope="col">{t("csv.f.date")}</th>
                    <th scope="col">{t("csv.f.description")}</th>
                    <th scope="col" className="amount">
                      {t("csv.f.amount")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {found.preview.map((ln, i) => (
                    <tr key={i}>
                      <td>{ln.booking_date}</td>
                      <td>{ln.description}</td>
                      <td className="amount">
                        {formatAmount(ln.amount, locale)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <button
            type="button"
            className="primary"
            disabled={!!found.error || save.isPending || importing}
            onClick={() =>
              save.mutate(mapping, { onSuccess: () => onImport() })
            }
          >
            {t("csv.saveAndImport")}
          </button>
          <ProblemMessage error={save.error} />
        </>
      ) : null}
    </section>
  );
}
