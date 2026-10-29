import * as SwitchPrimitive from "@radix-ui/react-switch";

import { cn } from "@/lib/utils";

export function Switch({
  id,
  checked,
  onCheckedChange,
  label,
  description,
  disabled,
}: {
  id: string;
  checked: boolean;
  onCheckedChange: (value: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-md py-xs">
      <label htmlFor={id} className="cursor-pointer">
        <span className="block text-body font-medium">{label}</span>
        {description && <span className="block text-link-sm text-ink-faint">{description}</span>}
      </label>
      <SwitchPrimitive.Root
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        className={cn(
          "relative mt-xxs h-6 w-11 shrink-0 cursor-pointer rounded-full bg-indigo-line transition-colors",
          "data-[state=checked]:bg-primary disabled:opacity-50",
        )}
      >
        <SwitchPrimitive.Thumb className="block size-5 translate-x-0.5 rounded-full bg-ink transition-transform data-[state=checked]:translate-x-[22px]" />
      </SwitchPrimitive.Root>
    </div>
  );
}
