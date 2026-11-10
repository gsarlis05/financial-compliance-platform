// Workspace export and deletion (M5-6).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiDownload } from "./client";

export interface Deletion {
  status: "NONE" | "REQUESTED" | "CONFIRMED";
  requested_at: string | null;
  confirmed_at: string | null;
  purge_after: string | null;
  grace_days: number;
}

export const useDeletion = (slug: string) =>
  useQuery({
    queryKey: ["deletion", slug],
    queryFn: () => api<Deletion>(`/w/${slug}/deletion`),
    enabled: !!slug,
    retry: false,
  });

export function useLifecycleMutations(slug: string) {
  const client = useQueryClient();
  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ["deletion", slug] }),
      client.invalidateQueries({ queryKey: ["workspace", slug] }),
    ]);
  const post = (path: string, body: object = {}) =>
    api<Deletion>(`/w/${slug}/deletion${path}`, { method: "POST", body });
  return {
    exportAll: useMutation({
      mutationFn: () => apiDownload(`/w/${slug}/export`),
    }),
    request: useMutation({ mutationFn: () => post(""), onSuccess: refresh }),
    confirm: useMutation({
      mutationFn: (workspaceName: string) =>
        post("/confirm", { workspace_name: workspaceName }),
      onSuccess: refresh,
    }),
    cancel: useMutation({
      mutationFn: () => post("/cancel"),
      onSuccess: refresh,
    }),
  };
}
