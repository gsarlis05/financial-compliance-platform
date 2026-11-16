// Fixed-asset register (M6-1); commencement and tax capital allowances (M6F-3).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { useScope } from "./hooks";

export type AssetCategory =
  | "BUILDINGS"
  | "MACHINERY"
  | "VEHICLES"
  | "IT_EQUIPMENT"
  | "FURNITURE"
  | "OTHER";
export type DepreciationMethod = "STRAIGHT_LINE" | "DECLINING_BALANCE";
export type Commencement = "PRORATA_DAYS" | "NEXT_MONTH" | "FULL_MONTH";
export type FirstYearRule = "FULL_YEAR" | "MONTHS_IN_USE" | "NONE";

export interface AssetInput {
  code: string;
  name: string;
  category: AssetCategory;
  asset_account_id: string;
  accumulated_account_id: string;
  expense_account_id: string;
  acquired_on: string;
  cost: string;
  residual_value: string;
  useful_life_months: number;
  method: DepreciationMethod;
  annual_rate?: string | null;
  available_on?: string | null;
  commencement: Commencement;
  allowance_class_code: string;
}

export interface FixedAsset extends AssetInput {
  id: string;
  disposed_on: string | null;
  disposal_proceeds: string | null;
  locked: boolean;
  accumulated: string;
  book_value: string;
  status: "ACTIVE" | "FULLY_DEPRECIATED" | "DISPOSED";
  disposal_gain: string | null;
}

export interface ScheduleRow {
  month: string;
  opening: string;
  depreciation: string;
  closing: string;
  accumulated: string;
  entry_id: string | null;
}

export interface AllowanceRow {
  tax_year: number;
  rate: string;
  allowance: string;
  written_down: string;
}

export interface AssetSchedule {
  asset_id: string;
  convention: string;
  rows: ScheduleRow[];
  allowance_rules: string;
  allowances: AllowanceRow[];
}

export interface AllowanceClassInput {
  code: string;
  name: string;
  annual_rate: string;
  first_year: FirstYearRule;
  effective_from: string;
  source: string;
}

export interface AllowanceClass extends AllowanceClassInput {
  id: string;
  created_at: string;
}

export function useAllowanceClasses() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["fixed-assets", entityId, "allowance-classes"],
    queryFn: () => api<AllowanceClass[]>(`${base}/capital-allowance-classes`),
  });
}

export interface DepreciationRun {
  id: string;
  month: string;
  total: string;
  assets: number;
  entry_id: string;
  entry_ref: string;
  entry_status: string;
  cancelled: boolean;
  created_at: string;
}

export function useFixedAssets(asOf: string) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["fixed-assets", entityId, asOf],
    queryFn: () =>
      api<FixedAsset[]>(`${base}/fixed-assets`, { query: { as_of: asOf } }),
  });
}

export function useAssetSchedule(assetId: string | null) {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["fixed-assets", entityId, "schedule", assetId],
    queryFn: () =>
      api<AssetSchedule>(`${base}/fixed-assets/${assetId}/schedule`),
    enabled: !!assetId,
  });
}

export function useDepreciationRuns() {
  const { base, entityId } = useScope();
  return useQuery({
    queryKey: ["fixed-assets", entityId, "runs"],
    queryFn: () => api<DepreciationRun[]>(`${base}/depreciation-runs`),
  });
}

export function useAssetMutations() {
  const { base, entityId } = useScope();
  const client = useQueryClient();
  const refresh = () =>
    client.invalidateQueries({ queryKey: ["fixed-assets", entityId] });
  return {
    create: useMutation({
      mutationFn: (body: AssetInput) =>
        api<FixedAsset>(`${base}/fixed-assets`, { method: "POST", body }),
      onSuccess: refresh,
    }),
    dispose: useMutation({
      mutationFn: ({
        id,
        ...body
      }: {
        id: string;
        disposed_on: string;
        proceeds: string;
      }) =>
        api<FixedAsset>(`${base}/fixed-assets/${id}/dispose`, {
          method: "POST",
          body,
        }),
      onSuccess: refresh,
    }),
    addClass: useMutation({
      mutationFn: (body: AllowanceClassInput) =>
        api<AllowanceClass>(`${base}/capital-allowance-classes`, {
          method: "POST",
          body,
        }),
      onSuccess: refresh,
    }),
    setClass: useMutation({
      mutationFn: ({ id, code }: { id: string; code: string }) =>
        api<FixedAsset>(`${base}/fixed-assets/${id}/allowance-class`, {
          method: "PUT",
          body: { allowance_class_code: code },
        }),
      onSuccess: refresh,
    }),
    prepare: useMutation({
      mutationFn: (month: string) =>
        api<DepreciationRun>(`${base}/depreciation-runs`, {
          method: "POST",
          body: { month },
        }),
      onSuccess: refresh,
    }),
  };
}
