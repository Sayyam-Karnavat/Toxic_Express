import { HeartHandshake } from "lucide-react";
import { Link } from "react-router-dom";

import { useMeta } from "@/api/meta";

/** Deliberately calm: no caps, no gradient, no motion (see plan section 14b). */
export function CrisisBanner({ compact }: { compact?: boolean }) {
  const { data } = useMeta();
  const resources = data?.crisis_resources ?? [];
  return (
    <aside role="note" className="mt-md rounded-lg border border-indigo-line bg-canvas p-md text-body">
      <div className="flex gap-sm">
        <HeartHandshake className="mt-0.5 size-5 shrink-0 text-link-cyan" aria-hidden />
        <div>
          <p className="font-medium">If you're going through something heavy, you don't have to carry it alone.</p>
          {!compact && (
            <ul className="mt-xs space-y-xxs text-link-sm text-ink-soft">
              {resources.map((r) => (
                <li key={r.name}>
                  {r.region}:{" "}
                  <a href={r.url} target="_blank" rel="noreferrer" className="text-link-cyan underline">
                    {r.name}
                  </a>
                  {r.phone && <> · call {r.phone}</>}
                </li>
              ))}
            </ul>
          )}
          <Link to="/help" className="mt-xs inline-block text-link-sm text-link-cyan underline">
            More support options
          </Link>
        </div>
      </div>
    </aside>
  );
}
