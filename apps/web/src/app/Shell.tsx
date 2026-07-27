import { Outlet } from "react-router-dom";

/**
 * The three-region desktop layout of `AGENTS.md` Section 14.1.
 *
 * The evidence rail is a region here and a sheet on smaller screens; it stays
 * empty until P5-09 gives it citations to show. The sidebar is a landmark now
 * so keyboard order and screen-reader structure are right before content
 * arrives, rather than being retrofitted around it.
 */
export function Shell() {
  return (
    <div className="grid h-full grid-cols-1 md:grid-cols-[280px_1fr] xl:grid-cols-[280px_1fr_360px]">
      <nav
        aria-label="Conversations"
        className="hidden border-r border-border bg-surface-raised md:block"
      >
        <div className="p-[var(--space-4)]">
          <span className="text-sm font-semibold tracking-tight">CodeAtlas</span>
        </div>
      </nav>

      <main id="main" className="min-w-0 overflow-y-auto">
        <Outlet />
      </main>

      <aside
        aria-label="Evidence"
        className="hidden border-l border-border bg-surface-raised xl:block"
      />
    </div>
  );
}
