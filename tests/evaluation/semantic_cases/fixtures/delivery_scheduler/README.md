# Delivery Scheduler

Hands work to couriers and retries what fails. The scheduler owns three
concerns: when to try again, which job is a duplicate of one already queued,
and when to stop trying at all.

It deliberately does not own delivery itself. A courier adapter performs the
call; the scheduler only decides whether and when it happens.
