# Packaging and installation

The packaged build is where CodeAtlas stops being a repository you run from
source. One rule governs it: **packaging changes no runtime contract.** A
packaged build answers exactly what a source checkout answers, and a difference
is a defect rather than a packaging detail (ADR-0007 decision 6).

## Building

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_package.ps1
```

Produces `dist/codeatlas-win64/` and `dist/codeatlas-win64.zip` (~44 MB).

The semantic-local package is deliberately explicit:

```powershell
uv sync --all-groups --extra semantic-local --frozen
powershell -ExecutionPolicy Bypass -File scripts/build_package.ps1 -SemanticLocal -SkipZip
```

That build includes the lazy optional dependency tree for local embeddings
(`sentence-transformers`, torch, LanceDB, and their native dependencies). The
default package stays deterministic and small; it lists semantic providers but
does not silently ship a model stack the user did not ask for.

**onedir, not onefile.** ADR-0007 says "a single executable", and `--onefile`
matches that wording more literally — but it re-extracts the whole bundle to
`%TEMP%` on *every* launch, which costs seconds of startup for a CLI and is a
well-known trigger for Windows antivirus heuristics. onedir starts instantly and
loads the native tree-sitter extensions from disk. It is still one command the
user runs, which is what the decision was really asking for. The deviation was
approved on 2026-07-28.

Two data sets are carried explicitly, because neither is a module:

| Bundled | Why it would otherwise be missing |
| --- | --- |
| `apps/web/dist` → `web` | `serve --web` would have nothing to serve |
| the SQL migrations | They are read through `importlib.resources`; a frozen build without them fails on a user's *first* run against a fresh database, which is the worst time to find out |

The build verifies its own artifact — a build whose executable cannot answer
`--help` is not a build — before zipping.

### In the gate

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -Package
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -Semantic -Package
```

Opt-in, because PyInstaller takes minutes and most runs of the gate change one
Python file. Without `-Package` the packaged smoke tests **skip with their
reason stated**, so a gate that never built the artifact does not read as one
that verified it.

Passing `-Semantic` with `-Package` builds the heavy semantic-local onedir
artifact and skips the zip step. That folder is the artifact
`scripts/measure_phase7_perf.py` starts.

## Installing

The unzipped folder works as-is from anywhere. The install script exists only so
that `codeatlas` is on PATH, which is how every documented command is written.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1 -Uninstall
```

**No elevation and no machine-wide state.** It changes exactly two things —
copies the build to `%LOCALAPPDATA%\CodeAtlas\app` and appends that folder to the
*user* PATH — and `-Uninstall` reverses exactly those two. An installer that
cannot be undone precisely is one users are right to distrust.

Uninstalling deliberately **does not remove your data**. The database lives in
`%LOCALAPPDATA%\CodeAtlas\data` and survives; the uninstaller says so and names
the folder rather than deciding for you.

Re-running the installer over an existing installation is the upgrade path: the
application folder is replaced, the data folder is untouched, and the database is
upgraded on first run after a checkpoint. It refuses while CodeAtlas is running
from that folder. Details in `docs/operations/upgrade-and-migration.md`.

## Running

```powershell
codeatlas serve --web           # API + web application on http://127.0.0.1:8000
codeatlas serve --web --open    # ...and open a browser
codeatlas serve                 # API only, for CLI and MCP users
```

`serve` prints the URL rather than opening it. Starting a server should not
steal focus, and it must not try to in a script or on a headless machine;
`--open` is there for the user who wants it.

**Loopback only.** `--host` refuses anything but a loopback address. Binding
beyond loopback needs authentication, a CSRF/CORS review, a revised threat
model, and explicit approval (`AGENTS.md` Section 25); until that exists the
flag refuses rather than exposing an unauthenticated service.

### One origin, no CORS

In development the browser talks to Vite, which proxies `/v1` to the API. A
packaged build has no Vite, so the API serves the built assets itself. Either
way the browser sees **one origin**, which is what lets the API keep registering
no CORS middleware at all.

Two routing rules make that safe:

- A client-side route like `/conversations/{id}` is not a file, so a deep link
  or a reload is answered with `index.html` and the router takes over.
- That fallback never swallows `/v1`. An unknown API path stays a JSON 404 —
  returning HTML to a client expecting JSON turns a clear failure into a parse
  error somewhere further from the cause.

If the web application was never built, `serve --web` **refuses and says so**
rather than starting an API-only server behind an empty page.

The app shell is intentionally not cacheable. `index.html` is the pointer to the
current hashed Vite assets, so it is served with
`Cache-Control: no-store, max-age=0, must-revalidate`; hashed files under
`/assets` can remain ordinary static assets. On 2026-08-04 the exact source
command `uv run codeatlas serve --web --open` was checked against the running
server: `/v1/repositories` returned 200, `/settings` returned the non-cacheable
shell, the served bundle contained the new Settings UI, and a browser probe
confirmed the Settings sidebar link performs a document navigation.

## What is verified, and what is not

`tests/end_to_end/test_packaged_build.py` runs against the real binary: it
starts, migrates a fresh database from the bundled migrations, registers and
indexes a repository (which is what proves the native tree-sitter extensions
load), resolves a symbol with evidence, and serves both the shell and `/v1` over
one origin.

It also **upgrades a database written by a real earlier build** and still
answers from what that build indexed — the same fixture the source-level upgrade
tests use, run through the binary, which is what proves the *bundled* migrations
are the ones being applied. See `docs/operations/upgrade-and-migration.md`.

Known qualification:

- The executable is **unsigned**. Windows SmartScreen will warn on first run.
  Code signing needs a certificate, which is a purchasing decision rather than
  an engineering one.
