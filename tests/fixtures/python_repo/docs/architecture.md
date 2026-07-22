# Payments Service Architecture

This document describes the payments subsystem.

## Layers

- **API** (`src/api/`) — FastAPI routers. Routers call **services**, never
  payment internals directly.
- **Services** (`src/services/`) — business logic. `PaymentService.capture`
  orchestrates idempotency and the gateway.
- **Payments** (`src/payments/`) — the `PaymentGateway` protocol and the
  `IdempotencyStore`.

## Payment capture flow

1. `capture_partner_payment` (`src/api/partner_payments.py`) receives the request.
2. It calls `PaymentService.capture` (`src/services/payment_service.py`).
3. `capture` claims the idempotency key via `IdempotencyStore.claim`
   (`src/payments/idempotency.py`) and charges through `PaymentGateway.charge`.

## Configuration

The database connection is controlled by the `DATABASE_URL` configuration key
(`src/config/settings.py`). Capture limits use `MAX_CAPTURE_AMOUNT`.

## Related decisions

See [ADR-0001: Idempotent payment capture](adr/0001-idempotency.md).
