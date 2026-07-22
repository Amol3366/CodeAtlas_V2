# ADR-0001: Idempotent payment capture

- **Status:** Accepted
- **Date:** 2026-01-15

## Context

Partners may retry capture requests. Charging twice for one payment is
unacceptable.

## Decision

`PaymentService.capture` MUST be idempotent on a caller-supplied
`idempotency_key`. The `IdempotencyStore.claim` method MUST return `False` for a
key that was already claimed, and `capture` MUST then return the previously
recorded transaction id rather than charging again.

## Consequences

- Every capture path MUST pass an `idempotency_key`.
- The store is currently in-memory; a durable backend is required before
  production (tracked separately).
