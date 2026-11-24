// One-person workspace (V1-1): whoever prepares something may also approve it. The server
// allows it only while the workspace has exactly one member; every such approval is recorded.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export interface OnePerson {
  enabled: boolean;
  active: boolean;
  blockers: string[];
}

export const useOnePerson = (slug: string, enabled = true) =>
  useQuery({
    queryKey: ["one-person", slug],
    queryFn: () => api<OnePerson>(`/w/${slug}/one-person`),
    enabled: !!slug && enabled,
    retry: false,
  });

export function useSetOnePerson(slug: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) =>
      api<OnePerson>(`/w/${slug}/one-person`, {
        method: "PUT",
        body: { enabled },
      }),
    onSuccess: (data) => {
      client.setQueryData(["one-person", slug], data);
      return client.invalidateQueries({ queryKey: ["workspace", slug] });
    },
  });
}
