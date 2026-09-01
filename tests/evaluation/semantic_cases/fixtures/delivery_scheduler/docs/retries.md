# Retry policy

A failed delivery is retried on a widening delay so a struggling courier is not
hammered while it recovers. The delay doubles each attempt and carries a random
offset, so a fleet of workers that all failed at the same moment does not come
back in step and repeat the pileup.

Retries stop when the job's deadline passes. A job that has run out of time is
not retried quietly -- it is moved aside so an operator can see it.
