import { Link } from "react-router-dom";

import { useCategoryLabel } from "@/api/meta";
import type { Category } from "@/types";

import { Badge } from "./ui/badge";

export function CategoryChip({ category }: { category: Category }) {
  const label = useCategoryLabel();
  return (
    <Link to={`/c/${category}`}>
      <Badge variant="magenta">{label(category)}</Badge>
    </Link>
  );
}

export function TagChip({ tag }: { tag: string }) {
  return (
    <Link to={`/t/${tag}`} className="text-link-sm text-link-cyan hover:underline">
      #{tag}
    </Link>
  );
}
