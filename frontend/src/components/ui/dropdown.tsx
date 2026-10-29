import * as Menu from "@radix-ui/react-dropdown-menu";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export const DropdownMenu = Menu.Root;
export const DropdownTrigger = Menu.Trigger;

export function DropdownContent({ children, align = "end" }: { children: ReactNode; align?: "start" | "end" }) {
  return (
    <Menu.Portal>
      <Menu.Content
        align={align}
        sideOffset={8}
        className="z-50 min-w-48 rounded-lg border border-indigo-line bg-surface-indigo p-xxs shadow-modal"
      >
        {children}
      </Menu.Content>
    </Menu.Portal>
  );
}

export function DropdownItem({
  children,
  onSelect,
  danger,
}: {
  children: ReactNode;
  onSelect?: () => void;
  danger?: boolean;
}) {
  return (
    <Menu.Item
      onSelect={onSelect}
      className={cn(
        "flex cursor-pointer items-center gap-xs rounded-md px-sm py-xs text-link-sm outline-none",
        "data-[highlighted]:bg-surface-raised",
        danger ? "text-danger" : "text-ink",
      )}
    >
      {children}
    </Menu.Item>
  );
}

export const DropdownSeparator = () => <Menu.Separator className="my-xxs h-px bg-indigo-line" />;
