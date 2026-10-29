import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useSearch } from "@/api/search";
import { PostCard } from "@/components/PostCard";
import { UserRow } from "@/components/UserRow";
import { EmptyState, ErrorState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { PageSpinner } from "@/components/ui/spinner";
import { errorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";

const TYPES = ["all", "posts", "users", "tags"] as const;

export default function SearchPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const type = (TYPES as readonly string[]).includes(params.get("type") ?? "") ? (params.get("type") as (typeof TYPES)[number]) : "all";
  const [draft, setDraft] = useState(q);
  useEffect(() => setDraft(q), [q]);
  const query = useSearch(q, type);

  return (
    <div className="space-y-md">
      <form
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          setParams({ q: draft.trim(), type });
        }}
      >
        <label htmlFor="search-page" className="sr-only">Search</label>
        <Input id="search-page" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Search rants, people, #tags" autoFocus />
      </form>
      <div className="flex gap-xxs rounded-lg bg-surface-indigo p-xxs" role="tablist" aria-label="Result type">
        {TYPES.map((t) => (
          <button key={t} role="tab" aria-selected={type === t} onClick={() => setParams({ q, type: t })} className={cn("min-h-10 rounded-md px-md text-link capitalize", type === t ? "bg-primary text-on-primary" : "text-ink-soft hover:text-ink")}>
            {t}
          </button>
        ))}
      </div>
      {q.trim().length < 2 ? (
        <EmptyState title="Search Toxic-Express">Type at least two characters.</EmptyState>
      ) : query.isLoading ? (
        <PageSpinner />
      ) : query.isError ? (
        <ErrorState message={errorMessage(query.error)} />
      ) : query.data && !query.data.posts.length && !query.data.users.length && !query.data.tags.length ? (
        <EmptyState title="No matches">Nobody has ranted about that yet. Maybe you should.</EmptyState>
      ) : (
        <div className="space-y-xl">
          {!!query.data?.tags.length && (
            <section>
              <h2 className="mb-sm font-display text-link-lg font-bold uppercase">Tags</h2>
              <div className="flex flex-wrap gap-xs">
                {query.data.tags.map((t) => (
                  <Link key={t.name} to={`/t/${t.name}`} className="rounded-pill bg-surface-indigo px-md py-xs text-link-sm hover:bg-surface-raised">
                    #{t.name} <span className="text-ink-faint">· {t.post_count}</span>
                  </Link>
                ))}
              </div>
            </section>
          )}
          {!!query.data?.users.length && (
            <section>
              <h2 className="mb-sm font-display text-link-lg font-bold uppercase">People</h2>
              <ul className="space-y-xs">{query.data.users.map((u) => <UserRow key={u.id} user={u} />)}</ul>
            </section>
          )}
          {!!query.data?.posts.length && (
            <section>
              <h2 className="mb-sm font-display text-link-lg font-bold uppercase">Rants</h2>
              <div className="space-y-md">{query.data.posts.map((p) => <PostCard key={p.id} post={p} />)}</div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
