import pytest
from envforge.models.fallback import with_retry, RETRYABLE
from envforge.models.errors import ErrorCategory, TransportError


def test_success_first_try():
    calls = []
    out = with_retry(lambda ep: calls.append(ep) or "ok", ["e1"], sleep=lambda s: None)
    assert out == "ok"
    assert calls == ["e1"]


def test_retries_then_succeeds_swapping_endpoints():
    seen = []

    def fn(ep):
        seen.append(ep)
        if len(seen) < 3:
            raise TransportError("503", status=503)
        return "ok"

    out = with_retry(fn, ["e1", "e2"], max_attempts=3, sleep=lambda s: None)
    assert out == "ok"
    assert seen == ["e1", "e2", "e1"]  # cycles endpoints


def test_non_retryable_raises_immediately():
    seen = []

    def fn(ep):
        seen.append(ep)
        raise TransportError("unauthorized", status=401)

    with pytest.raises(TransportError):
        with_retry(fn, ["e1", "e2"], max_attempts=3, sleep=lambda s: None)
    assert seen == ["e1"]  # no retry on AUTH


def test_exhausts_attempts_and_reraises():
    def fn(ep):
        raise TransportError("503", status=503)

    with pytest.raises(TransportError):
        with_retry(fn, ["e1"], max_attempts=2, sleep=lambda s: None)


def test_retryable_set():
    assert ErrorCategory.TIMEOUT in RETRYABLE
    assert ErrorCategory.AUTH not in RETRYABLE
