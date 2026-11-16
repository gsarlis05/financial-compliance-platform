import { type SyntheticEvent, useState } from "react";
import {
  useCounterparties,
  useCounterpartyMutations,
  usePaymentBehaviour,
  useSetDaysLateOverride,
} from "../api/hooks";
import type { CounterpartyKind, PaymentBehaviour } from "../api/types";
import {
  FieldError,
  Loading,
  Page,
  ProblemMessage,
} from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";

const KINDS: CounterpartyKind[] = [
  "CUSTOMER",
  "SUPPLIER",
  "BOTH",
  "EMPLOYEE",
  "TAX_AUTHORITY",
  "LENDER",
];
const EMPTY = {
  code: "",
  name: "",
  kind: "CUSTOMER" as CounterpartyKind,
  vat_no: "",
  email: "",
  payment_terms_days: 30,
};

function OverrideCell({ row }: { row: PaymentBehaviour }) {
  const { t } = useI18n();
  const save = useSetDaysLateOverride();
  const [value, setValue] = useState(
    row.override === null ? "" : String(row.override),
  );
  const label = `${t("pb.override")} ${row.counterparty_code}`;
  return (
    <form
      className="inline-form"
      onSubmit={(event: SyntheticEvent) => {
        event.preventDefault();
        save.mutate({
          id: row.counterparty_id,
          days: value.trim() === "" ? null : Number(value),
        });
      }}
    >
      <input
        type="number"
        min={-60}
        max={365}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        aria-label={label}
        className="narrow"
      />
      <button type="submit" disabled={save.isPending}>
        {t("pb.save")}
      </button>
      {row.override !== null ? (
        <button
          type="button"
          onClick={() => {
            setValue("");
            save.mutate({ id: row.counterparty_id, days: null });
          }}
        >
          {t("pb.clear")}
        </button>
      ) : null}
      <ProblemMessage error={save.error} />
    </form>
  );
}

function PaymentBehaviourSection() {
  const { t } = useI18n();
  const today = new Date().toISOString().slice(0, 10);
  const rows = usePaymentBehaviour(today);
  return (
    <section aria-labelledby="pb-heading">
      <h2 id="pb-heading">{t("pb.title")}</h2>
      <p className="muted">{t("pb.help")}</p>
      {rows.isPending ? <Loading /> : null}
      <ProblemMessage error={rows.error} />
      {rows.data?.length === 0 ? <p>{t("pb.none")}</p> : null}
      {rows.data?.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">{t("pb.customer")}</th>
                <th scope="col" className="amount">
                  {t("pb.observed")}
                </th>
                <th scope="col" className="amount">
                  {t("pb.sample")}
                </th>
                <th scope="col">{t("pb.override")}</th>
                <th scope="col" className="amount">
                  {t("pb.used")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.data.map((b) => (
                <tr key={b.counterparty_id} title={b.note}>
                  <td>
                    {b.counterparty_code}
                    <div className="muted small">{b.note}</div>
                  </td>
                  <td className="amount">
                    {b.observed_days_late ?? t("pb.notEnough")}
                  </td>
                  <td className="amount">{b.sample}</td>
                  <td>
                    <OverrideCell
                      key={`${b.counterparty_id}-${b.override}`}
                      row={b}
                    />
                  </td>
                  <td className="amount">{b.days_late}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

export function CounterpartiesPage() {
  const { t } = useI18n();
  const list = useCounterparties();
  const { create } = useCounterpartyMutations();
  const [form, setForm] = useState(EMPTY);

  function add(event: SyntheticEvent) {
    event.preventDefault();
    create.mutate(form, {
      onSuccess: () => setForm({ ...EMPTY, kind: form.kind }),
    });
  }

  return (
    <Page title={t("cp.title")}>
      {list.isPending ? <Loading /> : null}
      <ProblemMessage error={list.error} />
      {list.data?.length === 0 ? <p>{t("cp.none")}</p> : null}
      {list.data?.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">{t("cp.code")}</th>
                <th scope="col">{t("cp.name")}</th>
                <th scope="col">{t("cp.kind")}</th>
                <th scope="col">{t("cp.vat")}</th>
                <th scope="col" className="amount">
                  {t("cp.terms")}
                </th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((c) => (
                <tr key={c.id} className={c.status === "ACTIVE" ? "" : "muted"}>
                  <td>{c.code}</td>
                  <td>{c.name}</td>
                  <td>{t(`cp.kind.${c.kind}` as MessageKey)}</td>
                  <td>{c.vat_no}</td>
                  <td className="amount">{c.payment_terms_days}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <form className="panel form inline" onSubmit={add}>
        <h2>{t("cp.add")}</h2>
        <label>
          {t("cp.code")}
          <input
            value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value })}
            required
            maxLength={30}
          />
          <FieldError error={create.error} field="code" />
        </label>
        <label>
          {t("cp.name")}
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
            maxLength={200}
          />
        </label>
        <label>
          {t("cp.kind")}
          <select
            value={form.kind}
            onChange={(e) =>
              setForm({ ...form, kind: e.target.value as CounterpartyKind })
            }
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`cp.kind.${k}`)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("cp.vat")}
          <input
            value={form.vat_no}
            onChange={(e) => setForm({ ...form, vat_no: e.target.value })}
            maxLength={30}
          />
        </label>
        <label>
          {t("cp.email")}
          <input
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
        </label>
        <label>
          {t("cp.terms")}
          <input
            type="number"
            min={0}
            max={365}
            value={form.payment_terms_days}
            onChange={(e) =>
              setForm({ ...form, payment_terms_days: Number(e.target.value) })
            }
          />
        </label>
        <ProblemMessage error={create.error} />
        <button type="submit" disabled={create.isPending}>
          {t("cp.add")}
        </button>
      </form>
      <PaymentBehaviourSection />
    </Page>
  );
}
