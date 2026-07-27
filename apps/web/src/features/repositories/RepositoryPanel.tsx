import { useState } from "react";

import { Skeleton } from "../../components/Skeleton";
import { ApiError } from "../../lib/api";
import {
  useAddRepository,
  useDiagnostics,
  useIndexRepository,
  useRepositories,
  useRepositoryStatus,
} from "../../lib/queries";

/**
 * Repository onboarding, status, and diagnostics.
 *
 * The first surface that talks to a real backend, and deliberately so: every
 * number here is read from `/v1/repositories/*`. Nothing simulates progress —
 * a skeleton stands only for a request actually in flight, and a stage is
 * whatever the snapshot says it is (`AGENTS.md` Section 14.2).
 */

export function ErrorNotice({ error }: { readonly error: unknown }) {
  // The envelope's code appears beside the message so a user reporting a
  // problem can quote something stable. A stack trace is never rendered.
  const code = error instanceof ApiError ? error.code : "INTERNAL_ERROR";
  const message =
    error instanceof ApiError ? error.message : "The request failed.";
  return (
    <p role="alert" className="mt-[var(--space-3)] text-sm text-danger">
      <span className="font-medium">{message}</span>{" "}
      <code className="text-text-muted">{code}</code>
    </p>
  );
}

export function AddRepositoryForm() {
  const [path, setPath] = useState("");
  const add = useAddRepository();

  return (
    <form
      className="mt-[var(--space-4)]"
      onSubmit={(submitted) => {
        submitted.preventDefault();
        if (path.trim() !== "") add.mutate(path.trim());
      }}
    >
      <label htmlFor="repository-path" className="block text-sm font-medium">
        Add local repository
      </label>
      {/* The privacy statement belongs where the decision is made, not buried
          in settings. */}
      <p
        id="repository-privacy"
        className="mt-[var(--space-1)] text-sm text-text-muted"
      >
        CodeAtlas indexes this folder on your machine. No source, filenames, or
        derived content leave your computer.
      </p>
      <div className="mt-[var(--space-2)] flex gap-[var(--space-2)]">
        <input
          id="repository-path"
          aria-describedby="repository-privacy"
          className="min-w-0 flex-1 rounded-[var(--radius-md)] border border-border bg-surface px-[var(--space-3)] py-[var(--space-2)]"
          placeholder="Path to a local repository"
          value={path}
          onChange={(changed) => setPath(changed.target.value)}
        />
        <button
          type="submit"
          disabled={add.isPending || path.trim() === ""}
          className="rounded-[var(--radius-md)] bg-accent px-[var(--space-4)] py-[var(--space-2)] font-medium text-accent-contrast disabled:opacity-50"
        >
          {add.isPending ? "Adding…" : "Add"}
        </button>
      </div>
      {add.isError ? <ErrorNotice error={add.error} /> : null}
    </form>
  );
}

export function IndexStatusPanel({
  repositoryId,
}: {
  readonly repositoryId: string;
}) {
  const status = useRepositoryStatus(repositoryId);
  const index = useIndexRepository();

  if (status.isPending) {
    return <Skeleton className="h-20 w-full" label="Loading index status" />;
  }
  if (status.isError) return <ErrorNotice error={status.error} />;

  const snapshot = status.data.snapshot;
  return (
    <section aria-labelledby="index-status" className="mt-[var(--space-6)]">
      <h2 id="index-status" className="text-sm font-semibold">
        Index status
      </h2>
      {snapshot === null ? (
        <p className="mt-[var(--space-2)] text-sm text-text-muted">
          This repository has not been indexed yet.
        </p>
      ) : (
        <dl className="mt-[var(--space-2)] grid grid-cols-2 gap-[var(--space-2)] text-sm">
          {/* The word carries the meaning; color only reinforces it. */}
          <dt className="text-text-muted">Freshness</dt>
          <dd data-testid="freshness">{snapshot.freshness}</dd>
          <dt className="text-text-muted">Files</dt>
          <dd>{status.data.file_count}</dd>
          <dt className="text-text-muted">Symbols</dt>
          <dd>{status.data.symbol_count}</dd>
          <dt className="text-text-muted">Parse errors</dt>
          <dd>{status.data.parse_error_count}</dd>
        </dl>
      )}
      <button
        type="button"
        onClick={() => index.mutate(repositoryId)}
        disabled={index.isPending}
        className="mt-[var(--space-3)] rounded-[var(--radius-md)] border border-border px-[var(--space-3)] py-[var(--space-1)] text-sm disabled:opacity-50"
      >
        {index.isPending ? "Indexing…" : "Index now"}
      </button>
      {index.isError ? <ErrorNotice error={index.error} /> : null}
      {status.data.warnings.length > 0 ? (
        <ul className="mt-[var(--space-3)] text-sm text-stale">
          {status.data.warnings.map((warning) => (
            <li key={warning}>
              <code>{warning}</code>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

export function DiagnosticsPanel({
  repositoryId,
}: {
  readonly repositoryId: string;
}) {
  const diagnostics = useDiagnostics(repositoryId);

  if (diagnostics.isPending) {
    return <Skeleton className="h-16 w-full" label="Loading diagnostics" />;
  }
  if (diagnostics.isError) return <ErrorNotice error={diagnostics.error} />;

  const skipped = Object.entries(diagnostics.data.skipped_by_reason);
  return (
    <section aria-labelledby="diagnostics" className="mt-[var(--space-6)]">
      <h2 id="diagnostics" className="text-sm font-semibold">
        Diagnostics
      </h2>
      {skipped.length === 0 ? (
        <p className="mt-[var(--space-2)] text-sm text-text-muted">
          No files were skipped.
        </p>
      ) : (
        <ul className="mt-[var(--space-2)] text-sm">
          {skipped.map(([reason, count]) => (
            <li key={reason}>
              <code>{reason}</code>: {count}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function RepositoryPanel({
  onSelect,
}: {
  readonly onSelect?: (repositoryId: string) => void;
}) {
  const repositories = useRepositories();
  const [selected, setSelected] = useState<string | null>(null);

  if (repositories.isPending) {
    return <Skeleton className="h-24 w-full" label="Loading repositories" />;
  }
  if (repositories.isError) return <ErrorNotice error={repositories.error} />;

  const active = selected ?? repositories.data[0]?.repository_id ?? null;

  if (repositories.data.length === 0) {
    return (
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Add your first repository
        </h1>
        <AddRepositoryForm />
      </div>
    );
  }

  return (
    <div>
      <label htmlFor="repository-select" className="block text-sm font-medium">
        Repository
      </label>
      <select
        id="repository-select"
        className="mt-[var(--space-2)] rounded-[var(--radius-md)] border border-border bg-surface px-[var(--space-2)] py-[var(--space-1)]"
        value={active ?? ""}
        onChange={(changed) => {
          setSelected(changed.target.value);
          onSelect?.(changed.target.value);
        }}
      >
        {repositories.data.map((repository) => (
          <option key={repository.repository_id} value={repository.repository_id}>
            {repository.display_name}
          </option>
        ))}
      </select>
      {active !== null ? (
        <>
          <IndexStatusPanel repositoryId={active} />
          <DiagnosticsPanel repositoryId={active} />
        </>
      ) : null}
      <AddRepositoryForm />
    </div>
  );
}
