from scheduler.backoff import MAX_DELAY_SECONDS, next_delay


def test_delay_doubles_each_attempt() -> None:
    assert next_delay(1) == 2.0
    assert next_delay(2) == 4.0
    assert next_delay(3) == 8.0


def test_delay_is_capped() -> None:
    assert next_delay(20) == MAX_DELAY_SECONDS
