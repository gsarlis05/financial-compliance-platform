// Goals against scenarios (M7-7 for M7-5): a goal next to up to three shared scenarios, with the
// likely outcome, gap and status under each. Computed when asked; nothing is saved, no alert is
// raised and the goal never changes.
import { useState } from "react";
import { useGoalOutlooks, useScenarios } from "../api/scenarios";
import { Loading, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";

const MAX = 3;

export function GoalScenarios({ goalId }: { goalId: string }) {
  const { t } = useI18n();
  const shared = (useScenarios().data ?? []).filter(
    (s) => s.status === "SHARED",
  );
  const [chosen, setChosen] = useState<string[]>([]);
  const outlooks = useGoalOutlooks(goalId, chosen);
  const toggle = (id: string) =>
    setChosen((c) =>
      c.includes(id)
        ? c.filter((x) => x !== id)
        : c.length < MAX
          ? [...c, id]
          : c,
    );
  return (
    <section className="card" aria-labelledby="gs-title">
      <h2 id="gs-title">{t("gs.title")}</h2>
      <p>{t("gs.intro")}</p>
      {shared.length === 0 ? <p className="hint">{t("gs.none")}</p> : null}
      <fieldset>
        <legend>{t("gs.choose")}</legend>
        {shared.map((s) => (
          <label key={s.id}>
            <input
              type="checkbox"
              checked={chosen.includes(s.id)}
              disabled={!chosen.includes(s.id) && chosen.length >= MAX}
              onChange={() => toggle(s.id)}
            />
            {s.name}
          </label>
        ))}
      </fieldset>
      {outlooks.isLoading ? <Loading /> : null}
      {outlooks.error ? <ProblemMessage error={outlooks.error} /> : null}
      {outlooks.data ? (
        <div className="table-scroll">
          <table>
            <caption>{t("gs.caption")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("gs.plan")}</th>
                <th scope="col">{t("gs.projected")}</th>
                <th scope="col">{t("gs.gap")}</th>
                <th scope="col">{t("gs.status")}</th>
                <th scope="col">{t("gs.how")}</th>
              </tr>
            </thead>
            <tbody>
              {outlooks.data.map((o) => (
                <tr key={o.label}>
                  <th scope="row">
                    {o.label === "Base" ? t("sc.legendBase") : o.label}
                    {o.nature === "HYPOTHETICAL" ? (
                      <span className="badge nature-hypothetical">
                        {" "}
                        {t("nature.HYPOTHETICAL")}
                      </span>
                    ) : null}
                  </th>
                  {o.applicable ? (
                    <>
                      <td className="num">{o.projected ?? "–"}</td>
                      <td className="num">{o.gap ?? "–"}</td>
                      <td>{t(`goal.status.${o.status}` as MessageKey)}</td>
                      <td>{o.note}</td>
                    </>
                  ) : (
                    <td colSpan={4}>{o.reason}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <p className="hint">{t("gs.nothingSaved")}</p>
    </section>
  );
}
