import { useState } from "react";
import { Link, useParams } from "react-router";
import { apiUrl } from "../api/client";
import {
  useAgeing,
  useAllocationMutations,
  useOpenItems,
  useScope,
} from "../api/hooks";
import { BUCKETS, type Side } from "../api/types";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

function OpenItems({
  counterpartyId,
  asOf,
}: {
  counterpartyId: string;
  asOf: string;
}) {
  const { t, locale } = useI18n();
  const { slug = "", entityId = "" } = useParams();
  const items = useOpenItems(asOf, counterpartyId);
  const { autoAllocate } = useAllocationMutations();
  return (
    <section className="panel" aria-label={t("ar.items")}>
      <div className="actions">
        <button
          type="button"
          disabled={autoAllocate.isPending}
          onClick={() => autoAllocate.mutate({ counterpartyId, asOf })}
        >
          {t("ar.autoMatch")}
        </button>
      </div>
      <ProblemMessage error={items.error ?? autoAllocate.error} />
      {items.isPending ? <Loading /> : null}
      {items.data?.length === 0 ? (
        <p className="muted">{t("ar.allSettled")}</p>
      ) : null}
      {items.data?.length ? (
        <table>
          <thead>
            <tr>
              <th scope="col">{t("ar.date")}</th>
              <th scope="col">{t("ar.document")}</th>
              <th scope="col">{t("ar.kind")}</th>
              <th scope="col">{t("ar.due")}</th>
              <th scope="col" className="amount">
                {t("ar.amount")}
              </th>
              <th scope="col" className="amount">
                {t("ar.open")}
              </th>
            </tr>
          </thead>
          <tbody>
            {items.data.map((i) => (
              <tr key={i.line_id}>
                <td>{i.accounting_date}</td>
                <td>
                  <Link to={`/w/${slug}/e/${entityId}/entries/${i.entry_id}`}>
                    {i.entry_ref}
                  </Link>
                  {i.reference ? (
                    <span className="muted"> · {i.reference}</span>
                  ) : null}
                  {i.disputed ? (
                    <span className="tag"> {t("ar.disputed")}</span>
                  ) : null}
                </td>
                <td>{t(`ar.kind.${i.kind}` as MessageKey)}</td>
                <td
                  className={
                    i.kind === "INVOICE" && i.days_overdue > 0 ? "warn" : ""
                  }
                >
                  {i.kind === "INVOICE" ? i.due_date : ""}
                </td>
                <td className="amount">{formatAmount(i.amount, locale)}</td>
                <td className="amount">
                  {formatAmount(i.open_amount, locale)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

export function ReceivablesPage() {
  const { t, locale } = useI18n();
  const { base } = useScope();
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10));
  const [side, setSide] = useState<Side>("RECEIVABLE");
  const [selected, setSelected] = useState("");
  const report = useAgeing(asOf, side);
  return (
    <Page
      title={t("ar.title")}
      actions={
        <a
          className="button"
          href={apiUrl(`${base}/reports/ageing.csv`, { as_of: asOf, side })}
        >
          {t("tb.export")}
        </a>
      }
    >
      <div className="form inline">
        <label>
          {t("tb.asOf")}
          <input
            type="date"
            value={asOf}
            onChange={(e) => setAsOf(e.target.value)}
          />
        </label>
        <label>
          {t("ar.side")}
          <select
            value={side}
            onChange={(e) => {
              setSide(e.target.value as Side);
              setSelected("");
            }}
          >
            <option value="RECEIVABLE">{t("ar.side.RECEIVABLE")}</option>
            <option value="PAYABLE">{t("ar.side.PAYABLE")}</option>
          </select>
        </label>
      </div>
      {report.isPending ? <Loading /> : null}
      <ProblemMessage error={report.error} />
      {report.data ? (
        <>
          <p
            className={report.data.reconciles ? "notice" : "notice warn"}
            data-testid="reconciliation"
          >
            {report.data.reconciles
              ? t("ar.reconciles")
              : t("ar.doesNotReconcile")}{" "}
            {formatAmount(report.data.control_balance, locale)}
          </p>
          {report.data.rows.length === 0 ? (
            <p className="muted">{t("ar.none")}</p>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th scope="col">{t("cp.title")}</th>
                    {BUCKETS.map((b) => (
                      <th scope="col" className="amount" key={b}>
                        {t(`ar.bucket.${b}`)}
                      </th>
                    ))}
                    <th scope="col" className="amount">
                      {t("ar.unapplied")}
                    </th>
                    <th scope="col" className="amount">
                      {t("tb.total")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {report.data.rows.map((r) => (
                    <tr
                      key={r.counterparty_id}
                      className={
                        selected === r.counterparty_id ? "selected" : ""
                      }
                    >
                      <td>
                        <button
                          type="button"
                          className="link-button"
                          aria-expanded={selected === r.counterparty_id}
                          onClick={() =>
                            setSelected(
                              selected === r.counterparty_id
                                ? ""
                                : r.counterparty_id,
                            )
                          }
                        >
                          {r.counterparty_code} · {r.counterparty_name}
                        </button>
                      </td>
                      {BUCKETS.map((b) => (
                        <td className="amount" key={b}>
                          {r.buckets[b] === "0.00"
                            ? ""
                            : formatAmount(r.buckets[b], locale)}
                        </td>
                      ))}
                      <td className="amount">
                        {r.unapplied === "0.00"
                          ? ""
                          : formatAmount(r.unapplied, locale)}
                      </td>
                      <td className="amount">
                        {formatAmount(r.total, locale)}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <th scope="row">{t("tb.total")}</th>
                    {BUCKETS.map((b) => (
                      <td className="amount" key={b}>
                        {formatAmount(report.data.totals[b], locale)}
                      </td>
                    ))}
                    <td className="amount">
                      {formatAmount(report.data.unapplied, locale)}
                    </td>
                    <td className="amount">
                      {formatAmount(report.data.total, locale)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
          {selected ? (
            <OpenItems counterpartyId={selected} asOf={asOf} />
          ) : null}
        </>
      ) : null}
    </Page>
  );
}
