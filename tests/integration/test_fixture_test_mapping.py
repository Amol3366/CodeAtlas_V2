"""End-to-end proof that fixtures, helpers, and strict edges compose.

Every prior task tested one layer in isolation: the parser that spots
`@pytest.fixture`, the resolver that follows one helper hop, the impact
engine that ranks gap reasons by precedence. None of those unit tests
touch SQLite, the indexer, or Git. This test does, so it is the only one
that would catch a break between the layers.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection

import pytest

from codeatlas.application.change_analysis import ChangeAnalysisRequest
from codeatlas.application.container import ApplicationServices, build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import ChangeAnalysisReport, GapReasonCode
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

# Base source: three symbols, each reachable by exactly one path, so each
# gap reason assertion below can only pass for the intended reason.
BASE_ORDERS_PY = (
    "class Order:\n"
    "    def __init__(self):\n"
    "        self.amount = 0\n"
    "\n"
    "\n"
    "def total(order):\n"
    "    return order.amount\n"
    "\n"
    "\n"
    "def unused_helper():\n"
    "    return 0\n"
)

# Edited after the base commit, so the impact engine sees these three
# symbols as changed and considers them candidates for `test_gaps`.
TARGET_ORDERS_PY = (
    "class Order:\n"
    "    kind = 'sales'\n"
    "\n"
    "    def __init__(self):\n"
    "        self.amount = 0\n"
    "\n"
    "\n"
    "def total(order):\n"
    "    return order.amount + 1\n"
    "\n"
    "\n"
    "def unused_helper():\n"
    "    return 1\n"
)

ROOT_CONFTEST_PY = (
    # `import orders` + `orders.Order()` rather than `from orders import
    # Order`: the strict import-and-call pass matches an IMPORTS relation's
    # target symbol against a CALLS target in the same file. A module import
    # only names the module as imported, not `Order` itself, so this fixture
    # cannot accidentally satisfy the strict pass on its own -- it only
    # produces the CALLS edge that the fixture-mediation pass follows.
    "import pytest\n"
    "\n"
    "import orders\n"
    "\n"
    "\n"
    "@pytest.fixture\n"
    "def store():\n"
    "    return orders.Order()\n"
)

TESTS_CONFTEST_PY = (
    "import pytest\n"
    "\n"
    "\n"
    "@pytest.fixture\n"
    "def clock():\n"
    "    return 0\n"
)

# test_total: fixture-mediated to Order (via the `store` fixture only).
# test_via_helper: helper-mediated to total (via `_build`, one hop, and
#   `_build` itself is never called by anything strict).
# test_direct: strict edge to unused_helper (import AND call, directly).
TEST_ORDERS_PY = (
    # Imports are deliberately *local* to each function rather than shared at
    # module scope. A shared top-level import would be visible to every test
    # in the file, and then any test that merely calls the corresponding
    # helper would look like it both imports and calls the symbol directly,
    # collapsing helper-mediated into strict.
    "def test_total(store):\n"
    "    assert store is not None\n"
    "\n"
    "\n"
    "def _build():\n"
    "    # `import orders` + `orders.total(...)`, for the same reason as the\n"
    "    # root fixture above: it must produce a CALLS edge without also\n"
    "    # satisfying the strict import-and-call pass on `_build` itself.\n"
    "    import orders\n"
    "\n"
    "    return orders.total({'amount': 1})\n"
    "\n"
    "\n"
    "def test_via_helper():\n"
    "    _build()\n"
    "\n"
    "\n"
    "def test_direct():\n"
    "    from orders import unused_helper\n"
    "\n"
    "    assert unused_helper() == 0\n"
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "PATH": os.environ.get("PATH", ""),
            "GIT_CONFIG_GLOBAL": str(root / ".gitconfig-absent"),
            "GIT_CONFIG_SYSTEM": str(root / ".gitconfig-absent"),
        },
    )


@dataclass
class Harness:
    services: ApplicationServices
    connection: Connection
    repository_id: str
    root: Path


@pytest.fixture()
def repo(tmp_path: Path) -> Iterator[Harness]:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()

    (root / "src" / "orders.py").write_text(BASE_ORDERS_PY, encoding="utf-8")
    (root / "conftest.py").write_text(ROOT_CONFTEST_PY, encoding="utf-8")
    (root / "tests" / "conftest.py").write_text(TESTS_CONFTEST_PY, encoding="utf-8")
    (root / "tests" / "test_orders.py").write_text(TEST_ORDERS_PY, encoding="utf-8")

    # Commit the base tree first: the working-tree analysis diffs against
    # this commit, so editing before committing would produce a clean diff
    # and an empty report.
    _git(root, "init", "-b", "main")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")

    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(root))
        )
        yield Harness(
            services=services,
            connection=connection,
            repository_id=repository.repository_id,
            root=root,
        )


def index_and_analyze(repo: Harness) -> ChangeAnalysisReport:
    repo.services.indexing.index(repo.repository_id)
    (repo.root / "src" / "orders.py").write_text(TARGET_ORDERS_PY, encoding="utf-8")
    return repo.services.change_analysis.analyze_working_tree(
        ChangeAnalysisRequest(repository_id=repo.repository_id)
    )


def test_the_pipeline_maps_fixtures_helpers_and_gaps(repo: Harness) -> None:
    report = index_and_analyze(repo)
    reasons = {item.qualified_name: item.reason for item in report.test_gap_reasons}

    # Fixture-mediated: still a gap, explained.
    assert "Order" in report.test_gaps
    assert reasons["Order"] is GapReasonCode.FIXTURE_MEDIATED_ONLY

    # Helper-mediated: still a gap, explained.
    assert "total" in report.test_gaps
    assert reasons["total"] is GapReasonCode.HELPER_MEDIATED_ONLY

    # Strict import-and-call: not a gap at all.
    assert "unused_helper" not in report.test_gaps

    # Every gap carries exactly one reason.
    assert sorted(report.test_gaps) == sorted(reasons)

    # The contract did not move.
    assert report.contract_version == "1.1"
