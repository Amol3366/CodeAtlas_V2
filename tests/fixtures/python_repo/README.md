# payments-python (fixture)

A small but realistic FastAPI payments service used as a CodeAtlas evaluation
fixture. Contains classes, routes, tests, configuration, and documentation with
an ADR.

Key symbols:
- `PaymentService.capture` — `src/services/payment_service.py`
- `IdempotencyStore.claim` — `src/payments/idempotency.py`
- `capture_partner_payment` (route) — `src/api/partner_payments.py`
- `AuthService.authenticate` — `src/services/auth_service.py`
- `login` (route) — `src/api/auth_routes.py`

This directory is fixture data. It is intentionally NOT part of the CodeAtlas
package and is never installed.
