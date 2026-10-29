import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { Appeal, EntityType, ModAction, ModActionKind, QueueItem, ReportReason } from "@/types";

import { keys } from "./keys";

export function useModQueue() {
  return useQuery({
    queryKey: keys.modQueue,
    queryFn: () => api<{ items: QueueItem[] }>("/admin/queue"),
    refetchInterval: 60_000,
  });
}

export function useAudit() {
  return useQuery({ queryKey: keys.audit, queryFn: () => api<{ items: ModAction[] }>("/admin/audit") });
}

export function useAppeals() {
  return useQuery({ queryKey: keys.appeals, queryFn: () => api<{ items: Appeal[] }>("/admin/appeals") });
}

export function useModAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      entity_type: EntityType;
      entity_id: string;
      action: ModActionKind;
      reason?: string;
      suspend_days?: number;
    }) => api<ModAction>("/admin/actions", { method: "POST", body }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["admin"] }),
  });
}

export function useResolveAppeal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, accept, note }: { id: string; accept: boolean; note: string }) =>
      api<Appeal>(`/admin/appeals/${id}/resolve`, { method: "POST", body: { accept, note } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["admin"] }),
  });
}

export const safetyApi = {
  report: (entity_type: EntityType, entity_id: string, reason: ReportReason, note: string) =>
    api("/reports", { method: "POST", body: { entity_type, entity_id, reason, note } }),
  appeal: (action_id: string, message: string) => api("/appeals", { method: "POST", body: { action_id, message } }),
};
