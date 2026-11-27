// Who has checked the platform's rules and the projection engine, and when (brief 27, #254).
import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import { useScope } from "./hooks";

export type ReviewStatus =
  | "PENDING"
  | "OWNER_CHECKED"
  | "PROFESSIONALLY_VERIFIED";

export interface Review {
  subject: string;
  status: ReviewStatus;
  on: string | null;
  by: string;
  note: string;
  label: string;
}

export function useReviews() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["reviews", entityId],
    queryFn: () => api<Review[]>(`${base}/reviews`),
    staleTime: 5 * 60 * 1000,
  });
}
