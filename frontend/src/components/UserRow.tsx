import { Link } from "react-router-dom";

import type { UserSummary } from "@/types";

import { Avatar } from "./ui/avatar";

export function UserRow({ user, action }: { user: UserSummary; action?: React.ReactNode }) {
  return (
    <li className="flex items-center justify-between gap-sm rounded-md bg-surface-indigo px-md py-sm">
      <Link to={`/u/${user.handle}`} className="flex min-w-0 items-center gap-sm">
        <Avatar src={user.avatar?.["96"]} name={user.display_name} />
        <span className="min-w-0">
          <span className="block truncate font-medium">{user.display_name}</span>
          <span className="block truncate text-link-sm text-ink-faint">
            @{user.handle}
            {user.headline && ` · ${user.headline}`}
          </span>
        </span>
      </Link>
      <div className="flex shrink-0 items-center gap-xs">
        <span className="text-link-sm text-ink-faint" title="Helper Score">★ {user.helper_score}</span>
        {action}
      </div>
    </li>
  );
}
