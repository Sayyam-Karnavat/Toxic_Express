import { NavLink, Outlet } from "react-router-dom";

import { cn } from "@/lib/utils";

const SECTIONS = [
  ["profile", "Profile"],
  ["account", "Account & security"],
  ["privacy", "Privacy"],
  ["content", "Content preferences"],
  ["notifications", "Notifications"],
  ["blocked", "Blocked & muted"],
  ["moderation", "Moderation history"],
] as const;

export default function SettingsLayout() {
  return (
    <div className="space-y-md">
      <h1 className="font-display text-heading-sm font-bold uppercase">Settings</h1>
      <div className="flex flex-col gap-md laptop:flex-row">
        <nav aria-label="Settings" className="flex shrink-0 gap-xxs overflow-x-auto rounded-lg bg-surface-indigo p-xxs laptop:w-56 laptop:flex-col">
          {SECTIONS.map(([path, label]) => (
            <NavLink
              key={path}
              to={`/settings/${path}`}
              className={({ isActive }) =>
                cn("min-h-10 whitespace-nowrap rounded-md px-md py-xs text-link", isActive ? "bg-primary text-on-primary" : "text-ink-soft hover:text-ink")
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="min-w-0 flex-1 space-y-md">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
