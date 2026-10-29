import { useEffect, useRef } from "react";

import { Button } from "./ui/button";

/** Loads the next page when scrolled into view, with a button fallback. */
export function InfiniteLoader({
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
}: {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => unknown;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node || !hasNextPage) return;
    const observer = new IntersectionObserver(
      (entries) => entries[0]?.isIntersecting && !isFetchingNextPage && fetchNextPage(),
      { rootMargin: "600px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  if (!hasNextPage) return null;
  return (
    <div ref={ref} className="flex justify-center py-xl">
      <Button variant="ghost" onClick={() => fetchNextPage()} loading={isFetchingNextPage}>
        Load more
      </Button>
    </div>
  );
}
