class HistoryNotFoundError(LookupError):
    """历史快照不存在。"""


class HistorySnapshotError(RuntimeError):
    """历史 JSON 无法通过当前公开 schema 校验。"""
