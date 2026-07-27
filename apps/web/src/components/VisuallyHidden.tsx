import type { ReactNode } from "react";

/** Text for assistive technology only — never color or shape alone. */
export function VisuallyHidden({ children }: { readonly children: ReactNode }) {
  return <span className="sr-only">{children}</span>;
}
