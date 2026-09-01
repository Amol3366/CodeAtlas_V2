"""The loop that drains the queue."""

from scheduler.backoff import next_delay, spread
from scheduler.deadlines import Deadline, is_expired, park
from scheduler.queue import Job, WorkQueue


def run_once(queue: WorkQueue, deadline: Deadline, now: float) -> str:
    """Attempt one job and decide what happens to it next."""
    job = queue.take()
    if job is None:
        return "idle"
    if is_expired(deadline, now):
        return park(job.job_id, "deadline passed")
    wait = spread(next_delay(job.attempt))
    return f"retry:{job.job_id}:{wait:.2f}"


def requeue(queue: WorkQueue, job: Job) -> bool:
    """Put a failed job back with its attempt count advanced."""
    return queue.submit(Job(job.job_id, job.courier, job.attempt + 1))
