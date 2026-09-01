"""How long to wait before trying a failed delivery again."""

import random

BASE_DELAY_SECONDS = 2.0
MAX_DELAY_SECONDS = 300.0


def next_delay(attempt: int) -> float:
    """Seconds to wait before retry number ``attempt``.

    The wait doubles with each attempt so a courier that is struggling gets
    progressively more room to recover instead of being hammered at a fixed
    rate. The growth is capped, because past a few minutes a longer wait stops
    buying anything and only delays the operator finding out.
    """
    if attempt < 1:
        raise ValueError("attempt must be at least 1")
    delay = BASE_DELAY_SECONDS * (2 ** (attempt - 1))
    return min(delay, MAX_DELAY_SECONDS)


def spread(delay: float) -> float:
    """Offset a delay by a random fraction so retries do not arrive together.

    When a courier fails, every worker holding one of its jobs fails at the
    same moment and would otherwise come back at exactly the same moment too,
    reproducing the pileup that caused the failure. Scattering each wait breaks
    that synchronisation.
    """
    if delay < 0:
        raise ValueError("delay must not be negative")
    return delay * (1.0 + random.random() * 0.5)
