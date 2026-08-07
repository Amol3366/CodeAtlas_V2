import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChangedSymbols } from "./ChangedSymbols";
import type { ChangedFile, ChangedSymbol } from "./useAnalysis";

function symbol(overrides: Partial<ChangedSymbol> = {}): ChangedSymbol {
  return {
    qualified_name: "orders.Order.total",
    symbol_kind: "METHOD",
    change_kind: "modified",
    file_path: "src/orders.py",
    target_start_line: 40,
    target_end_line: 52,
    confidence: 1,
    derivation: "deterministic",
    public: true,
    signature_changed: false,
    ...overrides,
  } as ChangedSymbol;
}

function file(overrides: Partial<ChangedFile> = {}): ChangedFile {
  return {
    path: "pyproject.toml",
    change_kind: "modified",
    content_hash_changed: true,
    ...overrides,
  } as ChangedFile;
}

describe("ChangedSymbols", () => {
  it("shows each changed symbol with its file and lines", () => {
    render(<ChangedSymbols symbols={[symbol()]} files={[]} />);

    expect(screen.getByText("orders.Order.total")).toBeInTheDocument();
    expect(screen.getByText(/src\/orders\.py/)).toBeInTheDocument();
  });

  it("lists a changed file that produced no symbol", () => {
    // A deleted config file is a real change with no symbol to attach to.
    render(<ChangedSymbols symbols={[]} files={[file()]} />);

    expect(screen.getByText("pyproject.toml")).toBeInTheDocument();
  });

  it("does not repeat a file that already has a changed symbol", () => {
    render(
      <ChangedSymbols
        symbols={[symbol()]}
        files={[file({ path: "src/orders.py" })]}
      />,
    );

    expect(screen.getAllByText(/src\/orders\.py/)).toHaveLength(1);
  });

  it("says so when nothing differs", () => {
    render(<ChangedSymbols symbols={[]} files={[]} />);

    expect(screen.getByText(/No files differ/i)).toBeInTheDocument();
  });
});
