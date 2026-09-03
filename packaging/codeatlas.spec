# PyInstaller spec: two executables, one shared onedir bundle.
#
# **Why a spec at all.** The build was a command-line PyInstaller invocation
# until 2026-09-04, which is simpler and cannot express what is needed here:
# two entry points sharing one folder. `pyinstaller a.py b.py` does not build
# two programs -- it builds one Analysis over both scripts. Only a spec can
# declare two `EXE`s and hand both to a single `COLLECT`.
#
# **Why two executables and not a subcommand.** An MCP client launches the
# server itself and configures it as a command; `codeatlas-mcp.exe` is the name
# a client stanza points at, matching the `codeatlas-mcp` console script a
# source install already provides. The alternative -- `codeatlas.exe mcp` --
# would have been less packaging risk and a different published surface from
# the one source users have, and keeping the two identical is the rule
# `packaging/entry.py` exists to enforce.
#
# The bundle is shared, so the second executable costs kilobytes rather than
# another copy of torch. That is the whole reason both go through one COLLECT.
#
# Inputs arrive as environment variables set by `scripts/build_package.ps1`,
# which still owns *what* is built. This file owns only *how* it is assembled.

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(os.environ["CODEATLAS_BUILD_ROOT"])
SEMANTIC = os.environ.get("CODEATLAS_BUILD_SEMANTIC") == "1"

# Four data sets that are not modules, so analysis will never find them. Each
# was carried explicitly for a reason recorded in build_package.ps1; the two
# `.scm` sets were missing on 2026-08-19 and the artifact could not run at all.
datas = [
    (os.environ["CODEATLAS_BUILD_WEB"], "web"),
    (os.environ["CODEATLAS_BUILD_MIGRATIONS"], "codeatlas/storage/sqlite/migrations"),
    (os.environ["CODEATLAS_BUILD_QUERIES"], "codeatlas/parsing/query_backed/queries"),
]
binaries: list = []
hiddenimports: list = []

for grammar in (
    "tree_sitter_java",
    "tree_sitter_go",
    "tree_sitter_rust",
    "tree_sitter_scala",
):
    datas += collect_data_files(grammar)

hiddenimports += collect_submodules("uvicorn")

# `run_stdio` imports anyio and the mcp server modules *inside the function*,
# deliberately, so the `mcp` package is only required when the server actually
# starts. Analysis does follow function-level imports, but the mcp server
# resolves transports and types dynamically, so the submodules are collected
# rather than trusted to static analysis. Getting this wrong produces exactly
# the ADR-0065 failure shape: an executable that starts and then dies on its
# first real request.
for package in ("mcp", "anyio"):
    hiddenimports += collect_submodules(package)

if SEMANTIC:
    for package in (
        "huggingface_hub",
        "lancedb",
        "pyarrow",
        "safetensors",
        "sentence_transformers",
        "sklearn",
        "tokenizers",
        "torch",
        "transformers",
    ):
        package_datas, package_binaries, package_hidden = collect_all(package)
        datas += package_datas
        binaries += package_binaries
        hiddenimports += package_hidden


def _analysis(script: str):
    return Analysis(  # noqa: F821  (PyInstaller injects this)
        [str(ROOT / "packaging" / script)],
        pathex=[str(ROOT / "src")],
        binaries=binaries,
        datas=datas,
        hiddenimports=hiddenimports,
        hookspath=[],
        runtime_hooks=[],
        excludes=[],
        noarchive=False,
    )


cli_analysis = _analysis("entry.py")
mcp_analysis = _analysis("mcp_entry.py")

cli_pyz = PYZ(cli_analysis.pure)  # noqa: F821
mcp_pyz = PYZ(mcp_analysis.pure)  # noqa: F821

cli_exe = EXE(  # noqa: F821
    cli_pyz,
    cli_analysis.scripts,
    [],
    exclude_binaries=True,
    name="codeatlas",
    console=True,
)

mcp_exe = EXE(  # noqa: F821
    mcp_pyz,
    mcp_analysis.scripts,
    [],
    exclude_binaries=True,
    name="codeatlas-mcp",
    console=True,
)

# One COLLECT for both. The binaries and datas are the same objects in both
# analyses, and COLLECT deduplicates by destination, so the shared payload is
# written once.
COLLECT(  # noqa: F821
    cli_exe,
    mcp_exe,
    cli_analysis.binaries,
    cli_analysis.datas,
    mcp_analysis.binaries,
    mcp_analysis.datas,
    strip=False,
    upx=False,
    name="codeatlas",
)
