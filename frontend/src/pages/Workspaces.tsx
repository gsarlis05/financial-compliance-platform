import { type SyntheticEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useCreateWorkspace, useEntities, useWorkspaces } from "../api/hooks";
import { FieldError, Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";

export function WorkspacesPage() {
  const { t } = useI18n();
  const workspaces = useWorkspaces();
  const create = useCreateWorkspace();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [kind, setKind] = useState("BUSINESS");
  const [entityName, setEntityName] = useState("");

  function submit(event: SyntheticEvent) {
    event.preventDefault();
    create.mutate(
      { name, kind, ...(kind === "BUSINESS" ? { entity_name: entityName } : {}) },
      { onSuccess: (ws) => void navigate(`/w/${ws.slug}`) },
    );
  }

  return (
    <Page title={t("ws.title")}>
      {workspaces.isPending ? <Loading /> : null}
      <ProblemMessage error={workspaces.error} />
      {workspaces.data?.length === 0 ? <p>{t("ws.none")}</p> : null}
      <ul className="cards">
        {(workspaces.data ?? []).map((w) => (
          <li key={w.slug} className={`card kind-border-${w.kind.toLowerCase()}`}>
            <Link to={`/w/${w.slug}`}>
              <strong>{w.name}</strong>
              <span className={`kind kind-${w.kind.toLowerCase()}`}>{t(`kind.${w.kind}` as MessageKey)}</span>
            </Link>
          </li>
        ))}
      </ul>
      <form className="panel form" onSubmit={submit}>
        <h2>{t("ws.create")}</h2>
        <label>
          {t("ws.name")}
          <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
          <FieldError error={create.error} field="name" />
        </label>
        <label>
          {t("ws.kind")}
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {(["BUSINESS", "PERSONAL", "FIRM"] as const).map((k) => (
              <option key={k} value={k}>
                {t(`kind.${k}`)}
              </option>
            ))}
          </select>
        </label>
        {kind === "BUSINESS" ? (
          <label>
            {t("ws.entityName")}
            <input value={entityName} onChange={(e) => setEntityName(e.target.value)} required maxLength={200} />
            <FieldError error={create.error} field="entity_name" />
          </label>
        ) : null}
        <ProblemMessage error={create.error} />
        <button type="submit" disabled={create.isPending}>
          {t("ws.create")}
        </button>
      </form>
    </Page>
  );
}

/** /w/:slug goes straight to the first legal entity's journal. */
export function WorkspaceHome() {
  const { slug = "" } = useParams();
  const entities = useEntities(slug);
  const navigate = useNavigate();
  const first = entities.data?.[0];
  useEffect(() => {
    if (first) {
      void navigate(`/w/${slug}/e/${first.id}/entries`, { replace: true });
    }
  }, [first, navigate, slug]);
  return entities.error ? <ProblemMessage error={entities.error} /> : <Loading />;
}
