# Runbook

## A customer says they were charged but got no email

Confirmation is the last step of placing an order, after the charge. Check the
notifier's record for the reference before assuming the charge failed.

## Stock looks wrong after a cancellation

Cancelling releases the reserved units. If the same order was cancelled twice
the second attempt is refused, so a drift usually means the reservation was
never recorded rather than that it was released twice.

## Deliveries are running late

There is a delay notice the service can send, but nothing calls it
automatically today. It has to be triggered by hand.
