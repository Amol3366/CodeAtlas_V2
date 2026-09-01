"""The pending work queue and its duplicate suppression."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Job:
    """One delivery attempt, identified by the caller's own key."""

    job_id: str
    courier: str
    attempt: int = 1


@dataclass
class WorkQueue:
    """Jobs waiting to be handed to a courier."""

    _pending: list[Job] = field(default_factory=list)
    _seen: set[str] = field(default_factory=set)

    def submit(self, job: Job) -> bool:
        """Queue a job unless the same one is already waiting.

        A caller that retries its own request -- a timed-out HTTP call, a
        replayed webhook -- must not cause the parcel to be sent twice. The
        job's key is remembered, so submitting it again is accepted and
        ignored rather than rejected with an error the caller cannot act on.
        """
        if job.job_id in self._seen:
            return False
        self._seen.add(job.job_id)
        self._pending.append(job)
        return True

    def take(self) -> Job | None:
        """The next job to attempt, or ``None`` when nothing is waiting."""
        if not self._pending:
            return None
        return self._pending.pop(0)
