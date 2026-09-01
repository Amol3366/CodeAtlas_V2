"""When to give up on a delivery."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Deadline:
    """The moment after which a job must no longer be attempted."""

    expires_at: float


def is_expired(deadline: Deadline, now: float) -> bool:
    """Whether the job has run out of time to be attempted again."""
    return now >= deadline.expires_at


def park(job_id: str, reason: str) -> str:
    """Set an out-of-time job aside where an operator will see it.

    A job that can no longer be retried is not dropped and not logged and
    forgotten. It is moved to a holding area with the reason attached, because
    a delivery that silently stopped being attempted is indistinguishable from
    one that succeeded, and the difference matters to the customer waiting.
    """
    if not job_id:
        raise ValueError("job_id is required")
    return f"parked:{job_id}:{reason}"
