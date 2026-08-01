/**
 * The harness backend: a real CodeAtlas API, seeded and restartable.
 *
 * Everything here exists to make one thing possible — stopping the server and
 * starting it again against the same database. That is what proves persistence
 * survives a backend restart, and it cannot be proved against a server whose
 * lifetime Playwright owns via `webServer`.
 *
 * The database is therefore seeded once, separately from serving, and the
 * process is spawned and killed from inside the test worker.
 */

import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { appendFileSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
/** Repository root: `apps/web/e2e/support` → four levels up. */
export const repoRoot = resolve(here, "..", "..", "..", "..");

const pythonExecutable = join(repoRoot, ".venv", "Scripts", "python.exe");
const posixPython = join(repoRoot, ".venv", "bin", "python");
const harnessScript = join(repoRoot, "scripts", "e2e_backend.py");

export const apiPort = Number(process.env["CODEATLAS_E2E_API_PORT"] ?? 8123);
export const workdir = join(repoRoot, ".e2e-tmp");

export interface SeedResult {
  readonly database: string;
  readonly repository_id: string;
  readonly repository_path: string;
  readonly onboarding_repository_path: string;
  readonly snapshot_id: string;
  readonly file_count: number;
  readonly symbol_count: number;
}

function python(): string {
  return process.platform === "win32" ? pythonExecutable : posixPython;
}

/**
 * Create the fixture repository and index it.
 *
 * The working directory is removed first: a suite that inherited the previous
 * run's snapshot would pass or fail for reasons no one could reproduce.
 */
export function seed(): SeedResult {
  rmSync(workdir, { recursive: true, force: true });
  const result = spawnSync(
    python(),
    [harnessScript, "seed", "--workdir", workdir],
    { cwd: repoRoot, encoding: "utf-8" },
  );
  if (result.status !== 0) {
    throw new Error(
      `Seeding the end-to-end database failed (exit ${String(result.status)}):\n` +
        `${result.stdout ?? ""}\n${result.stderr ?? ""}`,
    );
  }
  return JSON.parse(result.stdout) as SeedResult;
}

async function isListening(): Promise<boolean> {
  try {
    const response = await fetch(`http://127.0.0.1:${apiPort}/v1/repositories`);
    return response.ok;
  } catch {
    return false;
  }
}

async function waitFor(
  predicate: () => Promise<boolean>,
  what: string,
  timeoutMs = 30_000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await new Promise((done) => setTimeout(done, 150));
  }
  throw new Error(`Timed out waiting for ${what}.`);
}

/** One API process, stoppable and startable against a fixed database. */
export class HarnessBackend {
  #child: ChildProcess | null = null;

  constructor(private readonly database: string) {}

  get running(): boolean {
    return this.#child !== null;
  }

  async start(): Promise<void> {
    if (this.#child !== null) return;
    const child = spawn(
      python(),
      [
        harnessScript,
        "serve",
        "--database",
        this.database,
        "--port",
        String(apiPort),
      ],
      { cwd: repoRoot, stdio: ["ignore", "pipe", "pipe"] },
    );
    this.#child = child;
    // Every request the browser made, kept next to the database. A failing
    // browser test is otherwise a mystery about which side went wrong.
    const log = join(workdir, "api.log");
    const record = (chunk: Buffer): void => {
      appendFileSync(log, chunk.toString());
    };
    child.stdout?.on("data", record);
    child.stderr?.on("data", record);
    // Readiness is a successful request, not a log line: a message on stderr
    // says uvicorn intends to listen, not that it does.
    await waitFor(isListening, `the API on port ${String(apiPort)}`);
  }

  async stop(): Promise<void> {
    const child = this.#child;
    if (child === null) return;
    this.#child = null;
    if (process.platform === "win32" && child.pid !== undefined) {
      // `child.kill()` on Windows does not reliably take a Python process with
      // it; taskkill on the tree does.
      spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
        stdio: "ignore",
      });
    } else {
      child.kill("SIGTERM");
    }
    await waitFor(
      async () => !(await isListening()),
      "the API to stop listening",
    );
  }

  /** Stop and start again — the same database, a different process. */
  async restart(): Promise<void> {
    await this.stop();
    await this.start();
  }
}
