import logging

import pytest

from app.core.logging import SensitiveUrlFilter, configure_logging, redact_url_queries


def test_sensitive_url_filter_removes_query_and_fragment_from_parameterized_message() -> None:
    record = logging.LogRecord(
        "httpx",
        logging.INFO,
        __file__,
        1,
        'HTTP Request: %s %s "%s"',
        (
            "PUT",
            "https://mineru.example/upload/file?OSSAccessKeyId=id&Signature=secret#fragment",
            "200 OK",
        ),
        None,
    )

    assert SensitiveUrlFilter().filter(record) is True

    message = record.getMessage()
    assert message == 'HTTP Request: PUT https://mineru.example/upload/file "200 OK"'
    assert "OSSAccessKeyId" not in message
    assert "Signature" not in message
    assert "fragment" not in message


def test_redact_url_queries_handles_multiple_urls_and_preserves_paths() -> None:
    message = (
        "primary=https://example.test/a/b?token=secret "
        "callback=http://127.0.0.1:8000/health#debug"
    )

    redacted = redact_url_queries(message)

    assert redacted == (
        "primary=https://example.test/a/b callback=http://127.0.0.1:8000/health"
    )


def test_redact_url_queries_keeps_plain_message_and_url_without_query() -> None:
    message = "HTTP Request: GET https://example.test/api/v1/health 200 OK"

    assert redact_url_queries(message) == message


def test_configure_logging_installs_filter_once_on_existing_root_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_logger = logging.getLogger()
    handler = logging.StreamHandler()
    monkeypatch.setattr(root_logger, "handlers", [handler])

    configure_logging()
    configure_logging()

    filters = [item for item in handler.filters if isinstance(item, SensitiveUrlFilter)]
    assert len(filters) == 1
