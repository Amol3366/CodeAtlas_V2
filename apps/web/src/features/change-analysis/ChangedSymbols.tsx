import type { ChangedFile, ChangedSymbol } from "./useAnalysis";

/**
 * What changed.
 *
 * Files appear only when they produced no changed symbol. A deleted
 * configuration file is a real change with nothing to attach to, and dropping
 * it would under-report the diff; repeating a file that already has symbols
 * would pad it.
 */
export function ChangedSymbols({
  symbols,
  files,
}: {
  readonly symbols: readonly ChangedSymbol[];
  readonly files: readonly ChangedFile[];
}) {
  const covered = new Set(symbols.map((item) => item.file_path));
  const bare = files.filter((item) => !covered.has(item.path));

  if (symbols.length === 0 && bare.length === 0) {
    return (
      <p className="text-sm text-text-muted">
        No files differ between the two states.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <ul className="space-y-[var(--space-2)]">
        {symbols.map((item) => (
          <li
            key={`${item.file_path}:${item.qualified_name}`}
            className="text-sm"
          >
            <code className="font-medium">{item.qualified_name}</code>{" "}
            <span className="text-text-muted">
              {item.symbol_kind} · {item.change_kind} · {item.file_path}
              {item.target_start_line !== null &&
              item.target_start_line !== undefined
                ? ` ${item.target_start_line}–${item.target_end_line}`
                : ""}
            </span>
          </li>
        ))}
        {bare.map((item) => (
          <li key={item.path} className="text-sm">
            <code className="font-medium">{item.path}</code>{" "}
            <span className="text-text-muted">{item.change_kind}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
