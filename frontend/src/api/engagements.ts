// Engagement grants (M5-4): a client-owned workspace lets a firm in; the firm staffs it.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export type EngagementRole = "accountant" | "reviewer" | "read_only";

export interface Engagement {
  id: string;
  firm_name: string;
  scope_roles: EngagementRole[];
  legal_entity_id: string | null;
  valid_until: string;
  created_at: string;
  revoked_at: string | null;
  active: boolean;
}

export interface FirmEngagement {
  engagement_id: string;
  client_slug: string;
  client_name: string;
  client_kind: string;
  scope_roles: EngagementRole[];
  legal_entity_id: string | null;
  valid_until: string;
  staff: {
    id: string;
    membership_id: string;
    email: string;
    display_name: string;
  }[];
}

export interface Member {
  membership_id: string;
  email: string;
  display_name: string;
  status: string;
}

export const useGrants = (slug: string, enabled: boolean) =>
  useQuery({
    queryKey: ["engagements", slug],
    queryFn: () => api<Engagement[]>(`/w/${slug}/engagements`),
    enabled,
  });

export const useClientEngagements = (slug: string, enabled: boolean) =>
  useQuery({
    queryKey: ["client-engagements", slug],
    queryFn: () => api<FirmEngagement[]>(`/w/${slug}/client-engagements`),
    enabled,
  });

export const useMembers = (slug: string, enabled: boolean) =>
  useQuery({
    queryKey: ["members", slug],
    queryFn: () => api<Member[]>(`/w/${slug}/members`),
    enabled,
  });

export function useEngagementMutations(slug: string) {
  const client = useQueryClient();
  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ["engagements", slug] }),
      client.invalidateQueries({ queryKey: ["client-engagements", slug] }),
    ]);
  return {
    grant: useMutation({
      mutationFn: (body: {
        firm_slug: string;
        scope_roles: EngagementRole[];
        valid_until: string;
      }) => api<Engagement>(`/w/${slug}/engagements`, { method: "POST", body }),
      onSuccess: refresh,
    }),
    revoke: useMutation({
      mutationFn: (id: string) =>
        api<Engagement>(`/w/${slug}/engagements/${id}/revoke`, {
          method: "POST",
          body: {},
        }),
      onSuccess: refresh,
    }),
    addStaff: useMutation({
      mutationFn: ({
        id,
        membershipId,
      }: {
        id: string;
        membershipId: string;
      }) =>
        api(`/w/${slug}/client-engagements/${id}/staff`, {
          method: "POST",
          body: { membership_id: membershipId },
        }),
      onSuccess: refresh,
    }),
    removeStaff: useMutation({
      mutationFn: (staffId: string) =>
        api<null>(`/w/${slug}/client-engagements/staff/${staffId}/remove`, {
          method: "POST",
          body: {},
        }),
      onSuccess: refresh,
    }),
  };
}
