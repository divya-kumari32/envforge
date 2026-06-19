from envforge.models.errors import ErrorCategory, classify_error, TransportError


def test_auth_status():
    assert classify_error(TransportError("nope", status=401)) is ErrorCategory.AUTH


def test_budget_by_message():
    assert classify_error(TransportError("budget exceeded", status=400)) is ErrorCategory.BUDGET


def test_budget_by_status_402():
    assert classify_error(TransportError("payment required", status=402)) is ErrorCategory.BUDGET


def test_timeout_status_and_exc():
    assert classify_error(TransportError("slow", status=504)) is ErrorCategory.TIMEOUT
    assert classify_error(TimeoutError("timed out")) is ErrorCategory.TIMEOUT


def test_server_5xx():
    assert classify_error(TransportError("bad gateway", status=502)) is ErrorCategory.SERVER


def test_malformed():
    assert classify_error(ValueError("could not parse json")) is ErrorCategory.MALFORMED


def test_transport():
    assert classify_error(ConnectionError("reset")) is ErrorCategory.TRANSPORT


def test_unknown():
    assert classify_error(RuntimeError("???")) is ErrorCategory.UNKNOWN
