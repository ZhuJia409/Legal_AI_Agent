class DocumentParseError(Exception):
    """Raised when uploaded document parsing fails."""


class DocumentParserConfigurationError(DocumentParseError):
    """文档解析器缺少本地必需配置，重试文件本身无法解决。"""


class DocumentParserUpstreamError(DocumentParseError):
    """文档解析上游网络、超时或服务响应异常。"""
