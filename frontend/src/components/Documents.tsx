import { useState } from "react";
import { apiUrl } from "../api/client";
import { useDocuments, useScope } from "../api/hooks";
import { useI18n } from "../i18n/I18n";
import { Loading, ProblemMessage } from "./common";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.xlsx,.csv,.txt,.xml";

function size(bytes: number): string {
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.ceil(bytes / 1024)} KB`;
}

/** Supporting documents of a journal entry (M2-4): upload (virus-scanned, type-checked), list,
 * download. Documents are kept as evidence and cannot be deleted. */
export function DocumentsPanel({ entryId }: { entryId: string }) {
  const { t, locale } = useI18n();
  const { base } = useScope();
  const { list, upload } = useDocuments(entryId);
  const [file, setFile] = useState<File | null>(null);
  return (
    <section className="panel" aria-label={t("doc.title")}>
      <h2>{t("doc.title")}</h2>
      {list.isPending ? <Loading /> : null}
      <ProblemMessage error={list.error} />
      {list.data?.length === 0 ? (
        <p className="muted">{t("doc.none")}</p>
      ) : null}
      {list.data?.length ? (
        <ul className="documents">
          {list.data.map((d) => (
            <li key={d.id}>
              <a href={apiUrl(`${base}/documents/${d.id}/content`)}>
                {d.filename}
              </a>{" "}
              <span className="muted">
                {size(d.size)} ·{" "}
                {new Date(d.created_at).toLocaleDateString(
                  locale === "el" ? "el-GR" : "en-GB",
                )}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      <form
        className="form inline"
        onSubmit={(e) => {
          e.preventDefault();
          if (file) {
            upload.mutate(file);
          }
        }}
      >
        <label>
          {t("doc.file")}
          <input
            type="file"
            accept={ACCEPT}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <button type="submit" disabled={!file || upload.isPending}>
          {t("doc.upload")}
        </button>
      </form>
      <p className="muted">{t("doc.help")}</p>
      <ProblemMessage error={upload.error} />
    </section>
  );
}
