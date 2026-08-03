import { useEffect } from "react";
import { useLocation } from "react-router-dom";

const RELOADED_SIGNATURE_KEY = "codeatlas.reloadedBuildSignature";
// How long a reload attempt stays evidence of a loop. A reload that fixes the
// mismatch completes far inside this; anything older is a previous session.
const RELOAD_GUARD_MILLISECONDS = 10_000;

/**
 * Keep a long-lived packaged tab from navigating with an obsolete JS bundle.
 *
 * Vite dev handles this with HMR. The packaged/local API serves static built
 * files, so a tab opened before a rebuild keeps executing the old bundle until
 * a document reload happens. This hook turns that manual reload into an
 * automatic one after a route change, using the shell's hashed asset list as
 * the build identity.
 */
export function useReloadOnNewBuild() {
  const location = useLocation();

  useEffect(() => {
    const currentSignature = buildAssetSignature(
      extractBuildAssetPaths(document.documentElement.outerHTML),
    );
    if (currentSignature === "") return;

    let cancelled = false;
    void fetch("/", {
      cache: "no-store",
      headers: { Accept: "text/html" },
    })
      .then(async (response) => {
        if (cancelled || !response.ok) return;

        const nextSignature = buildAssetSignature(
          extractBuildAssetPaths(await response.text()),
        );
        if (nextSignature === "" || nextSignature === currentSignature) {
          forgetReloadedSignature();
          return;
        }

        if (reloadWasJustAttemptedFor(nextSignature)) return;
        rememberReloadedSignature(nextSignature);
        window.location.reload();
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
  }, [location.pathname, location.search]);
}

export function extractBuildAssetPaths(html: string): readonly string[] {
  const parsed = new DOMParser().parseFromString(html, "text/html");
  const paths = [
    ...Array.from(parsed.querySelectorAll<HTMLScriptElement>("script[src]")).map(
      (node) => node.getAttribute("src"),
    ),
    ...Array.from(
      parsed.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"][href]'),
    ).map((node) => node.getAttribute("href")),
  ];

  return Array.from(
    new Set(
      paths
        .map((path) => normalizeSameOriginAssetPath(path))
        .filter((path): path is string => path !== null),
    ),
  ).sort();
}

export function buildAssetSignature(paths: readonly string[]): string {
  return Array.from(new Set(paths)).sort().join("\n");
}

function normalizeSameOriginAssetPath(path: string | null): string | null {
  if (path === null || path.trim() === "") return null;

  try {
    const resolved = new URL(path, window.location.origin);
    if (resolved.origin !== window.location.origin) return null;
    if (!resolved.pathname.startsWith("/assets/")) return null;
    return `${resolved.pathname}${resolved.search}`;
  } catch {
    return null;
  }
}

/**
 * Whether we reloaded for this exact build moments ago.
 *
 * The guard exists for one case: a reload that does not fix the mismatch, which
 * would otherwise loop forever. That case resolves in milliseconds, so the
 * record is only meaningful while it is fresh.
 *
 * The freshness window is the whole point. `sessionStorage` survives browser
 * session restore, so a guard written by a reload that never completed comes
 * back with the restored tab — and a signature-only check then suppresses the
 * very reload this hook exists to perform, leaving the tab on an old bundle
 * until the user reloads by hand. A stale record is not evidence of a loop; it
 * is evidence of a previous session.
 */
function reloadWasJustAttemptedFor(signature: string): boolean {
  let raw: string | null = null;
  try {
    raw = window.sessionStorage.getItem(RELOADED_SIGNATURE_KEY);
  } catch {
    return false;
  }
  if (raw === null) return false;

  try {
    const record: unknown = JSON.parse(raw);
    if (
      typeof record !== "object" ||
      record === null ||
      !("signature" in record) ||
      !("at" in record)
    ) {
      return false;
    }

    const { signature: recorded, at } = record as {
      signature: unknown;
      at: unknown;
    };
    if (recorded !== signature || typeof at !== "number") return false;

    // A negative age means the clock moved; treat it as expired rather than
    // trusting it, since the failure it would cause is a suppressed reload.
    const age = Date.now() - at;
    return age >= 0 && age < RELOAD_GUARD_MILLISECONDS;
  } catch {
    // An unparseable record predates this format, or was written by something
    // else. Either way it is not proof of a loop.
    return false;
  }
}

function rememberReloadedSignature(signature: string): void {
  try {
    window.sessionStorage.setItem(
      RELOADED_SIGNATURE_KEY,
      JSON.stringify({ signature, at: Date.now() }),
    );
  } catch {
    // A blocked sessionStorage should not block the freshness reload itself.
  }
}

function forgetReloadedSignature(): void {
  try {
    window.sessionStorage.removeItem(RELOADED_SIGNATURE_KEY);
  } catch {
    // Storage is a loop guard only; failure does not affect normal routing.
  }
}
