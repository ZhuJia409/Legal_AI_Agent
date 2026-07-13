import logging
import re
from urllib.parse import urlsplit, urlunsplit

_HTTP_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?)]}"


def redact_url_queries(value: str) -> str:
    """移除 HTTP(S) URL 的查询参数与 fragment，保留排障所需的目标路径。"""

    def replace(match: re.Match[str]) -> str:
        candidate = match.group(0)
        trailing = ""
        while candidate and candidate[-1] in _TRAILING_PUNCTUATION:
            trailing = candidate[-1] + trailing
            candidate = candidate[:-1]
        try:
            parsed = urlsplit(candidate)
            redacted = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        except ValueError:
            # 畸形 URL 也必须保守删除敏感后缀，日志脱敏失败不得影响业务请求。
            query_index = len(candidate)
            for separator in ("?", "#"):
                position = candidate.find(separator)
                if position >= 0:
                    query_index = min(query_index, position)
            redacted = candidate[:query_index]
        return redacted + trailing

    return _HTTP_URL_PATTERN.sub(replace, value)


class SensitiveUrlFilter(logging.Filter):
    """在 formatter 处理前固化并脱敏消息，兼容 httpx 的参数化日志。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            return True
        record.msg = redact_url_queries(message)
        record.args = ()
        return True


def configure_logging() -> None:
    """配置应用日志，并为所有根 handler 幂等安装 URL 脱敏。"""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if not any(isinstance(item, SensitiveUrlFilter) for item in handler.filters):
            handler.addFilter(SensitiveUrlFilter())
    logging.getLogger("legal_ai").setLevel(logging.INFO)
