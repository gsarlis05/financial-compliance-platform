import { type SyntheticEvent, useState } from "react";
import { useDimensionMutations, useDimensions } from "../api/hooks";
import type { Dimension, DimensionKind } from "../api/types";
import {
  FieldError,
  Loading,
  Page,
  ProblemMessage,
} from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";

const KINDS: DimensionKind[] = [
  "DEPARTMENT",
  "PROJECT",
  "COST_CENTRE",
  "CUSTOM",
];

function ValueForm({ dimension }: { dimension: Dimension }) {
  const { t } = useI18n();
  const { createValue } = useDimensionMutations();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  function add(event: SyntheticEvent) {
    event.preventDefault();
    createValue.mutate(
      { dimensionId: dimension.id, code, name },
      {
        onSuccess: () => {
          setCode("");
          setName("");
        },
      },
    );
  }
  return (
    <form className="form inline" onSubmit={add}>
      <label>
        {t("dim.code")}
        <input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          required
          maxLength={30}
        />
        <FieldError error={createValue.error} field="code" />
      </label>
      <label>
        {t("dim.name")}
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          maxLength={200}
        />
      </label>
      <ProblemMessage error={createValue.error} />
      <button type="submit" disabled={createValue.isPending}>
        {t("dim.addValue")} ({dimension.code})
      </button>
    </form>
  );
}

export function DimensionsPage() {
  const { t } = useI18n();
  const dimensions = useDimensions();
  const { createDimension, setValueStatus } = useDimensionMutations();
  const [form, setForm] = useState<{
    code: string;
    name: string;
    kind: DimensionKind;
  }>({
    code: "",
    name: "",
    kind: "DEPARTMENT",
  });

  function add(event: SyntheticEvent) {
    event.preventDefault();
    createDimension.mutate(form, {
      onSuccess: () => setForm({ code: "", name: "", kind: form.kind }),
    });
  }

  return (
    <Page title={t("dim.title")}>
      <p className="muted">{t("dim.help")}</p>
      {dimensions.isPending ? <Loading /> : null}
      <ProblemMessage error={dimensions.error ?? setValueStatus.error} />
      {dimensions.data?.length === 0 ? <p>{t("dim.none")}</p> : null}
      {(dimensions.data ?? []).map((d) => (
        <section key={d.id} className="panel" aria-labelledby={`dim-${d.id}`}>
          <h2 id={`dim-${d.id}`}>
            {d.code} · {d.name}{" "}
            <span className="muted">
              ({t(`dim.kind.${d.kind}` as MessageKey)})
            </span>
          </h2>
          {d.values.length ? (
            <table>
              <thead>
                <tr>
                  <th scope="col">{t("dim.code")}</th>
                  <th scope="col">{t("dim.name")}</th>
                  <th scope="col">
                    <span className="visually-hidden">{t("je.status")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {d.values.map((v) => (
                  <tr
                    key={v.id}
                    className={v.status === "ACTIVE" ? "" : "muted"}
                  >
                    <td>{v.code}</td>
                    <td>
                      {v.name}
                      {v.status === "ACTIVE" ? null : (
                        <span> · {t("dim.inactive")}</span>
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="link-button"
                        onClick={() =>
                          setValueStatus.mutate({
                            valueId: v.id,
                            status:
                              v.status === "ACTIVE" ? "INACTIVE" : "ACTIVE",
                          })
                        }
                      >
                        {v.status === "ACTIVE"
                          ? t("dim.deactivate")
                          : t("dim.activate")}{" "}
                        {v.code}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          <ValueForm dimension={d} />
        </section>
      ))}
      <form className="panel form inline" onSubmit={add}>
        <h2>{t("dim.add")}</h2>
        <label>
          {t("dim.code")}
          <input
            value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value })}
            required
            maxLength={20}
          />
          <FieldError error={createDimension.error} field="code" />
        </label>
        <label>
          {t("dim.name")}
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
            maxLength={100}
          />
        </label>
        <label>
          {t("dim.kind")}
          <select
            value={form.kind}
            onChange={(e) =>
              setForm({ ...form, kind: e.target.value as DimensionKind })
            }
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`dim.kind.${k}`)}
              </option>
            ))}
          </select>
        </label>
        <ProblemMessage error={createDimension.error} />
        <button type="submit" disabled={createDimension.isPending}>
          {t("dim.add")}
        </button>
      </form>
    </Page>
  );
}
