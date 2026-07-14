"""案件材料分段与服务端证据引用回填。"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.schemas.case_analysis import CaseSourceRef


class UnknownCaseSourceError(ValueError):
    """模型返回了当前材料快照中不存在的段落号。"""


@dataclass(frozen=True, slots=True)
class CaseEvidenceSegment:
    paragraph_id: str
    text: str


def segment_case_material(content: str) -> tuple[CaseEvidenceSegment, ...]:
    """按空行划分逻辑段落，保留段内换行并生成稳定编号。"""

    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ()
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", normalized) if item.strip()]
    return tuple(
        CaseEvidenceSegment(paragraph_id=f"p{index:04d}", text=text)
        for index, text in enumerate(paragraphs, start=1)
    )


def format_case_evidence(segments: Sequence[CaseEvidenceSegment]) -> str:
    """使用明确边界格式化提示词，避免材料内容与系统指令混淆。"""

    return "\n\n".join(f"[{item.paragraph_id}]\n{item.text}" for item in segments)


def resolve_source_refs(
    paragraph_ids: Sequence[str],
    segments: Sequence[CaseEvidenceSegment],
) -> list[CaseSourceRef]:
    index = {item.paragraph_id: item for item in segments}
    refs: list[CaseSourceRef] = []
    seen: set[str] = set()
    for paragraph_id in paragraph_ids:
        if paragraph_id in seen:
            continue
        segment = index.get(paragraph_id)
        if segment is None:
            raise UnknownCaseSourceError(f"unknown case paragraph_id: {paragraph_id}")
        seen.add(paragraph_id)
        refs.append(CaseSourceRef(paragraph_id=paragraph_id, quote=segment.text))
    return refs
