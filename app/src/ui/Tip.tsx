import * as Tooltip from "@radix-ui/react-tooltip";
import type { ReactElement, ReactNode } from "react";

export const TipProvider = Tooltip.Provider;

/** Hover/focus hint for icon buttons and disabled controls (wrap a focusable element). */
export function Tip({ label, children, side = "bottom" }: { label: ReactNode; children: ReactElement; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    <Tooltip.Root delayDuration={350}>
      <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className="tip" side={side} sideOffset={6} collisionPadding={8}>
          {label}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}
