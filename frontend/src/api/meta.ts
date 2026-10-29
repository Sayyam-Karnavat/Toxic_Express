import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { Category, Meta } from "@/types";

import { keys } from "./keys";

export function useMeta() {
  return useQuery({ queryKey: keys.meta, queryFn: () => api<Meta>("/meta"), staleTime: Infinity });
}

export function useCategoryLabel(): (c: Category) => string {
  const { data } = useMeta();
  return (c) => data?.categories.find((x) => x.value === c)?.label ?? c.replace("_", " ");
}
