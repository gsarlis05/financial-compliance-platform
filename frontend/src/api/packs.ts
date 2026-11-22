// Management report packs (M8): frozen snapshots, sections, commentary, risks, review, exports.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiUrl } from "./client";
import { useScope } from "./hooks";

export type PackStatus = "DRAFT" | "IN_REVIEW" | "FINAL" | "SUPERSEDED";
export type BlockStatus = "ok" | "empty" | "denied";
export const SECTION_KEYS = [
  "overview",
  "profitability",
  "cash",
  "working_capital",
  "budget",
  "kpis",
  "forecast",
  "risks",
  "goals",
  "commentary",
] as const;
export const COLUMN_KEYS = [
  "actual",
  "budget",
  "original_budget",
  "forecast",
  "prior_year",
  "variance",
] as const;

export interface Pack {
  id: string;
  family_id: string;
  version: number;
  supersedes_id: string | null;
  title: string;
  period_kind: "MONTH" | "QUARTER" | "YEAR";
  period_start: string;
  period_end: string;
  status: PackStatus;
  sections: string[];
  columns: string[];
  snapshot_hash: string;
  watermark: number;
  generated_at: string;
  created_by_id: string;
  created_at: string;
  submitted_at: string | null;
  reviewed_by_id: string | null;
  self_approved?: boolean; // finalised by its preparer in a one-person workspace (V1-1)
  review_note: string;
  finalised_at: string | null;
  superseded_at: string | null;
  blocks: Record<string, BlockStatus>;
}

export interface PackDetail extends Pack {
  blockers: string[];
}

export interface Cell {
  value: string | null;
  nature: string | null;
}

export interface Table {
  caption: string;
  caption_el: string;
  columns: { key: string; label: string; label_el: string }[];
  rows: {
    key: string;
    label: string;
    label_el: string;
    kind: string;
    display?: string;
    requires_explanation?: boolean;
    cells: Cell[];
  }[];
}

export interface Risk {
  ref: number;
  title: string;
  owner: string;
  status: "OPEN" | "MONITORING" | "CLOSED";
  mitigation: string;
}

export interface Section {
  key: string;
  title: string;
  title_el: string;
  status: BlockStatus;
  reason: string;
  notice: string;
  notice_el: string;
  tables: Table[];
  comment: string | null;
  risks: Risk[];
}

export function usePacks() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["packs", entityId],
    queryFn: () => api<Pack[]>(`${base}/report-packs`),
  });
}

export function usePack(id: string | null) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["pack", entityId, id],
    queryFn: () => api<PackDetail>(`${base}/report-packs/${id}`),
    enabled: !!id,
  });
}

export function usePackSections(id: string | null, lang: string) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["pack-sections", entityId, id, lang],
    queryFn: () =>
      api<{ pack: Pack; sections: Section[] }>(
        `${base}/report-packs/${id}/sections`,
        { query: { lang } },
      ),
    enabled: !!id,
  });
}

export function packExportUrl(
  base: string,
  id: string,
  format: "xlsx" | "pdf",
  lang: string,
): string {
  return apiUrl(`${base}/report-packs/${id}/export`, { format, lang });
}

export function usePackMutations(id: string | null) {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["packs", entityId] });
    void client.invalidateQueries({ queryKey: ["pack", entityId] });
    void client.invalidateQueries({ queryKey: ["pack-sections", entityId] });
  };
  const url = `${base}/report-packs/${id}`;
  const post = <T>(path: string, body: unknown = {}) =>
    api<T>(`${url}/${path}`, { method: "POST", body });
  return {
    create: useMutation({
      mutationFn: (body: {
        period_kind: string;
        month: string;
        title: string;
      }) => api<PackDetail>(`${base}/report-packs`, { method: "POST", body }),
      onSuccess: refresh,
    }),
    act: useMutation({
      mutationFn: ({
        what,
        note,
      }: {
        what: "regenerate" | "submit" | "return" | "finalise" | "new-version";
        note?: string;
      }) => post<PackDetail>(what, note === undefined ? {} : { note }),
      onSuccess: refresh,
    }),
    arrange: useMutation({
      mutationFn: (body: { sections: string[]; columns: string[] }) =>
        api<Pack>(`${url}/arrangement`, { method: "PUT", body }),
      onSuccess: refresh,
    }),
    comment: useMutation({
      mutationFn: (body: { section: string; text: string }) =>
        post<Record<string, string>>("comments", body),
      onSuccess: refresh,
    }),
    addRisk: useMutation({
      mutationFn: (body: Omit<Risk, "ref">) => post<Risk[]>("risks", body),
      onSuccess: refresh,
    }),
    changeRisk: useMutation({
      mutationFn: ({ ref, ...body }: Risk) =>
        api<Risk[]>(`${url}/risks/${ref}`, { method: "PUT", body }),
      onSuccess: refresh,
    }),
    removeRisk: useMutation({
      mutationFn: (ref: number) => post<Risk[]>(`risks/${ref}/remove`),
      onSuccess: refresh,
    }),
  };
}
