# Ordering architecture

## Layers

The service layer sequences the steps. The domain modules underneath it hold
no knowledge of each other's order, so a step can be reordered in one place.

## Why stock is held before the confirmation

Reserving units first means a customer is never told an order succeeded when
the warehouse could not fill it. The reservation is released again if the
order is later cancelled.

## Money is stored in minor units

Amounts are integers of cents rather than floating point, so repeated addition
across many lines cannot drift. Formatting back to a decimal string happens
only at the edge, when a human needs to read it.

## Retry and idempotency

Placing the same reference twice is not currently guarded. The repository
overwrites by reference, so a duplicate call re-runs the reservation and takes
stock a second time. This is a known gap.
