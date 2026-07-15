from pathlib import Path

import pytest

from app.services.contract_review.type_skills import (
    CONTRACT_TYPE_RULES,
    ContractTypeSkillError,
    load_contract_type_rules,
)


def test_contract_type_skill_registry_contains_34_safe_rule_packs() -> None:
    assert len(CONTRACT_TYPE_RULES) == 34
    for rule in CONTRACT_TYPE_RULES.values():
        assert rule.path.name.startswith("ct-")
        assert rule.path.suffix == ".md"
        assert ".." not in rule.path.parts


def test_load_contract_type_rules_reads_only_selected_rule_packs() -> None:
    loaded = load_contract_type_rules(["sale", "technology"])

    assert [item.code.value for item in loaded] == ["sale", "technology"]
    assert "买卖合同规则包" in loaded[0].content
    assert "技术合同规则包" in loaded[1].content


def test_load_contract_type_rules_rejects_unknown_or_excessive_codes() -> None:
    with pytest.raises(ContractTypeSkillError, match="未知合同类型"):
        load_contract_type_rules(["../../secret"])

    with pytest.raises(ContractTypeSkillError, match="最多加载 3 个"):
        load_contract_type_rules(["sale", "lease", "technology", "nda"])


def test_all_contract_type_rule_files_exist_under_skill_directory() -> None:
    roots = {rule.path.parent for rule in CONTRACT_TYPE_RULES.values()}
    assert len(roots) == 1
    root = roots.pop()
    assert root == Path(root).resolve()
    assert all(rule.path.is_file() for rule in CONTRACT_TYPE_RULES.values())


def test_all_contract_type_rule_files_are_structured_markdown() -> None:
    for rule in CONTRACT_TYPE_RULES.values():
        content = rule.path.read_text(encoding="utf-8")
        lines = content.splitlines()

        assert "\\n" not in content
        assert lines[0] == "---"
        assert f"code: {rule.code.value}" in lines[1:5]
        assert f'label: "{rule.label}"' in lines[1:5]
        assert lines[4] == "---"
        assert any(line.startswith("# ") for line in lines[5:])
        assert len(lines) >= 12


def test_special_review_skill_output_contract_matches_runtime_schema() -> None:
    skill_path = next(iter(CONTRACT_TYPE_RULES.values())).path.parent.parent / "SKILL.md"
    content = skill_path.read_text(encoding="utf-8")

    assert '"negotiation_strategy"' in content
    assert '"paragraph_ids"' in content
    assert "finding_id" in content
    assert "source_refs" in content
