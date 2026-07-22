# ADR-0002: Configuration via environment variables

- **Status:** Accepted
- **Date:** 2026-02-03

## Context

The platform runs in varied environments and MUST NOT ship secrets in files.

## Decision

All configuration MUST be provided through environment variables prefixed with
`WIDGET_`. The application MUST fail fast when `WIDGET_DATABASE_URL` is absent.

## Consequences

- No configuration file format is supported.
- Documentation MUST list every `WIDGET_`-prefixed key (see
  [Getting Started](../getting-started.md)).
