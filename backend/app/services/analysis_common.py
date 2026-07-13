from typing import Any

from app.schemas.analysis import AnalysisModule, AnalysisResponse, RiskLevel

LEGAL_DISCLAIMER = "本结果由人工智能生成，仅供参考，重大法律结论应由专业法律人士复核。"

LEGAL_ANALYSIS_SYSTEM_PROMPT = """
你是严谨的法律分析助手。你只能基于用户提供的文本进行分析，不得编造不存在的事实、
法条、案例或证据。请用中文输出，并且只返回一个 JSON 对象，不要输出 Markdown。
JSON 字段必须包含 summary、risk_level、findings、suggestions。
risk_level 只能是 low、medium、high。
""".strip()


def build_analysis_response(module: AnalysisModule, payload: dict[str, Any]) -> AnalysisResponse:
    return AnalysisResponse(
        module=module,
        summary=_normalize_text(payload.get("summary"), "暂无摘要。"),
        risk_level=_normalize_risk_level(payload.get("risk_level")),
        findings=_normalize_text_list(payload.get("findings")),
        suggestions=_normalize_text_list(payload.get("suggestions")),
        disclaimer=LEGAL_DISCLAIMER,
    )


def _normalize_text(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _normalize_text_list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        items = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return items or ["暂无明确结论。"]
    return ["暂无明确结论。"]


def _normalize_risk_level(value: Any) -> RiskLevel:
    if value in {"low", "medium", "high"}:
        return value
    return "medium"
