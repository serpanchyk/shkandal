import json
import logging

from shkandal_common.logging import ContextualJsonFormatter, bind_log_context


def test_json_formatter_adds_required_fields() -> None:
    formatter = ContextualJsonFormatter()
    record = logging.LogRecord(
        name="shkandal.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="ready",
        args=(),
        exc_info=None,
    )

    with bind_log_context(trace_id="trace-1", session_id="session-1", user_id="user-1"):
        payload = json.loads(formatter.format(record))

    assert payload["timestamp"]
    assert payload["name"] == "shkandal.test"
    assert payload["level"] == "INFO"
    assert payload["message"] == "ready"
    assert payload["trace_id"] == "trace-1"
    assert payload["session_id"] == "session-1"
    assert payload["user_id"] == "user-1"
