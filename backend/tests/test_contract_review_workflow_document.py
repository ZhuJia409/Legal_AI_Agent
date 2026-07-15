from pathlib import Path


def test_contract_review_workflow_documents_pdf_form_agent_separately() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    document = (
        repository_root
        / "docs"
        / "contract-review"
        / "architecture"
        / "合同审查-Agent-端到端流程.html"
    )
    html = document.read_text(encoding="utf-8")

    assert html.count('<pre class="mermaid">') == 11
    assert html.count('<section class="chapter">') == 11
    assert "8 个独立 Agent" in html
    assert "PDF 文书表单 Agent" in html
    assert "ToolStrategy" in html
    assert "模型不能生成或修改 LaTeX" in html
    assert "报告汇总 Agent" in html
    assert "固定 LaTeX 法律意见书模板" in html
    assert "Tectonic 编译 PDF" in html
