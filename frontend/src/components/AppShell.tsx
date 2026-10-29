import { Bell, Menu, Search, Shield, X } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useLogout } from "@/api/auth";
import { useMeta } from "@/api/meta";
import { useUnreadCount } from "@/api/notifications";
import { cn } from "@/lib/utils";
import { useAuth } from "@/store/auth";

import { Composer } from "./Composer";
import { Logo } from "./Logo";
import { Avatar } from "./ui/avatar";
import { Button } from "./ui/button";
import { DropdownContent, DropdownItem, DropdownMenu, DropdownSeparator, DropdownTrigger } from "./ui/dropdown";

const NAV = [
  { to: "/", label: "Feed", end: true },
  { to: "/trending", label: "Trending" },
  { to: "/solved", label: "Solved" },
];

function SearchBox({ onDone }: { onDone?: () => void }) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  return (
    <form
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        if (q.trim().length >= 2) {
          navigate(`/search?q=${encodeURIComponent(q.trim())}`);
          onDone?.();
        }
      }}
      className="relative"
    >
      <Search className="pointer-events-none absolute left-sm top-1/2 size-4 -translate-y-1/2 text-ink-faint" aria-hidden />
      <label htmlFor="global-search" className="sr-only">Search Toxic-Express</label>
      <input
        id="global-search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search rants, people, #tags"
        className="h-10 w-full rounded-pill border border-indigo-line bg-surface-indigo pl-xxl pr-md text-link-sm placeholder:text-ink-faint focus:border-primary focus:outline-none laptop:w-72"
      />
    </form>
  );
}

function NotificationBell() {
  const { data } = useUnreadCount();
  const unread = data?.unread ?? 0;
  return (
    <Link
      to="/notifications"
      className="relative inline-flex size-10 items-center justify-center rounded-full hover:bg-surface-indigo"
      aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
    >
      <Bell className="size-5" aria-hidden />
      {unread > 0 && (
        <span className="absolute right-1 top-1 min-w-5 rounded-pill bg-magenta-strong px-1 text-center text-[11px] font-semibold leading-5">
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </Link>
  );
}

function UserMenu() {
  const user = useAuth((s) => s.user);
  const logout = useLogout();
  const navigate = useNavigate();
  if (!user) return null;
  return (
    <DropdownMenu>
      <DropdownTrigger className="rounded-full" aria-label="Account menu">
        <Avatar src={user.avatar?.["96"]} name={user.display_name} />
      </DropdownTrigger>
      <DropdownContent>
        <div className="px-sm py-xs">
          <p className="font-medium">{user.display_name}</p>
          <p className="text-link-sm text-ink-faint">@{user.handle}</p>
        </div>
        <DropdownSeparator />
        <DropdownItem onSelect={() => navigate(`/u/${user.handle}`)}>Your profile</DropdownItem>
        <DropdownItem onSelect={() => navigate("/settings/profile")}>Settings</DropdownItem>
        {(user.role === "mod" || user.role === "admin") && (
          <DropdownItem onSelect={() => navigate("/mod")}>
            <Shield className="size-4" /> Moderation
          </DropdownItem>
        )}
        <DropdownItem onSelect={() => navigate("/help")}>Help & safety</DropdownItem>
        <DropdownSeparator />
        <DropdownItem onSelect={() => logout.mutate(false, { onSettled: () => navigate("/") })}>Log out</DropdownItem>
      </DropdownContent>
    </DropdownMenu>
  );
}

function NavBar({ onCompose }: { onCompose: () => void }) {
  const authed = useAuth((s) => s.status === "authenticated");
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  return (
    <header className="sticky top-0 z-30 border-b border-indigo-line bg-canvas/95 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-[1200px] items-center gap-md px-md tablet:px-xl">
        <button className="tablet:hidden" aria-label="Open menu" onClick={() => setMobileOpen(true)}>
          <Menu className="size-6" />
        </button>
        <Logo />
        <nav aria-label="Main" className="ml-md hidden gap-xxs tablet:flex">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                cn("rounded-sm px-sm py-xs text-link", isActive ? "bg-surface-indigo text-ink" : "text-ink-soft hover:text-ink")
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto hidden laptop:block">
          <SearchBox />
        </div>
        <div className="ml-auto flex items-center gap-xs laptop:ml-0">
          {authed ? (
            <>
              <Link to="/search" className="inline-flex size-10 items-center justify-center rounded-full hover:bg-surface-indigo laptop:hidden" aria-label="Search">
                <Search className="size-5" />
              </Link>
              <NotificationBell />
              <Button variant="green" size="sm" onClick={onCompose} className="hidden font-display uppercase tablet:inline-flex">
                Scream it
              </Button>
              <UserMenu />
            </>
          ) : (
            <>
              <Button asChild variant="quiet" size="sm">
                <Link to={`/login?next=${encodeURIComponent(location.pathname)}`}>Log in</Link>
              </Button>
              <Button asChild variant="green" size="sm" className="font-display uppercase">
                <Link to="/signup">Join</Link>
              </Button>
            </>
          )}
        </div>
      </div>
      {mobileOpen && <MobileDrawer onClose={() => setMobileOpen(false)} />}
    </header>
  );
}

function MobileDrawer({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-40 tablet:hidden" role="dialog" aria-modal="true" aria-label="Menu">
      <div className="absolute inset-0 bg-surface-black/70" onClick={onClose} />
      <div className="absolute inset-y-0 left-0 w-72 overflow-y-auto bg-canvas p-md">
        <div className="mb-md flex items-center justify-between">
          <Logo />
          <button aria-label="Close menu" onClick={onClose}>
            <X className="size-6" />
          </button>
        </div>
        <SearchBox onDone={onClose} />
        <nav aria-label="Mobile" className="mt-md flex flex-col">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} onClick={onClose} className="rounded-md px-sm py-sm text-link-lg">
              {n.label}
            </NavLink>
          ))}
        </nav>
        <Sidebar onNavigate={onClose} />
      </div>
    </div>
  );
}

/** DESIGN.md `ex-app-shell-row`: category rows with a Blurple active indicator. */
export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { data: meta } = useMeta();
  return (
    <nav aria-label="Categories" className="mt-md">
      <p className="mb-xs px-md text-link-sm font-medium uppercase tracking-wide text-ink-faint">Categories</p>
      <ul className="space-y-xxs">
        {meta?.categories.map((c) => (
          <li key={c.value}>
            <NavLink
              to={`/c/${c.value}`}
              onClick={onNavigate}
              className={({ isActive }) =>
                cn(
                  "relative flex min-h-10 items-center rounded-md px-md py-sm text-link",
                  isActive ? "bg-surface-indigo text-ink before:absolute before:inset-y-2 before:left-0 before:w-1 before:rounded-pill before:bg-primary" : "text-ink-soft hover:bg-surface-indigo hover:text-ink",
                )
              }
            >
              {c.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function Footer() {
  return (
    <footer className="mt-section border-t border-indigo-line bg-canvas px-md py-section tablet:px-xl">
      <div className="mx-auto max-w-[1200px]">
        <div className="grid gap-xl text-link tablet:grid-cols-3">
          <div>
            <p className="mb-sm font-medium text-ink-soft">Product</p>
            <ul className="space-y-xs">
              <li><Link to="/trending" className="hover:underline">Trending rants</Link></li>
              <li><Link to="/solved" className="hover:underline">Solved stories</Link></li>
            </ul>
          </div>
          <div>
            <p className="mb-sm font-medium text-ink-soft">Safety</p>
            <ul className="space-y-xs">
              <li><Link to="/help" className="hover:underline">Help & crisis resources</Link></li>
              <li><Link to="/help#rules" className="hover:underline">Community rules</Link></li>
            </ul>
          </div>
          <div>
            <p className="mb-sm font-medium text-ink-soft">Account</p>
            <ul className="space-y-xs">
              <li><Link to="/settings/privacy" className="hover:underline">Privacy settings</Link></li>
              <li><Link to="/settings/account" className="hover:underline">Your data</Link></li>
            </ul>
          </div>
        </div>
        <p aria-hidden className="mt-section select-none font-display text-[clamp(48px,13vw,170px)] font-bold uppercase leading-none tracking-tighter text-primary">
          Toxic-Express
        </p>
        <p className="mt-md text-link-sm text-ink-faint">Rant about situations, not people. © {new Date().getFullYear()} Toxic-Express.</p>
      </div>
    </footer>
  );
}

export function AppShell() {
  const [composing, setComposing] = useState(false);
  const status = useAuth((s) => s.status);
  const { pathname } = useLocation();
  const authed = status === "authenticated";
  const isLanding = status === "anonymous" && pathname === "/";
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-md focus:top-md focus:z-50 focus:rounded-sm focus:bg-primary focus:px-md focus:py-xs">
        Skip to content
      </a>
      <NavBar onCompose={() => setComposing(true)} />
      <div className="mx-auto flex w-full max-w-[1200px] flex-1 gap-xl px-md tablet:px-xl">
        <aside className={cn("hidden w-56 shrink-0", !isLanding && "laptop:block")}>
          <div className="sticky top-20">
            <Sidebar />
          </div>
        </aside>
        <main id="main" className="min-w-0 flex-1 py-xl">
          <Outlet context={{ compose: () => setComposing(true) }} />
        </main>
      </div>
      {authed && (
        <Button
          variant="green"
          onClick={() => setComposing(true)}
          className="fixed bottom-md right-md z-20 font-display uppercase shadow-float tablet:hidden"
        >
          Scream it
        </Button>
      )}
      <Footer />
      {composing && <Composer open={composing} onOpenChange={setComposing} />}
    </div>
  );
}

export function BareLayout() {
  return (
    <div className="mesh-bg flex min-h-screen flex-col">
      <header className="mx-auto flex h-16 w-full max-w-[1200px] items-center px-md tablet:px-xl">
        <Logo />
      </header>
      <main id="main" className="flex flex-1 items-center justify-center px-md py-xl">
        <Outlet />
      </main>
    </div>
  );
}
