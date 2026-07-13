"""34 类合同专项 Skill 的安全注册表和只读加载器。"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.schemas.contract_review import ContractTypeCode


class ContractTypeSkillError(ValueError):
    """专项规则请求不满足白名单或数量约束。"""


@dataclass(frozen=True)
class ContractTypeRule:
    code: ContractTypeCode
    label: str
    path: Path


@dataclass(frozen=True)
class LoadedContractTypeRule:
    code: ContractTypeCode
    label: str
    path: Path
    content: str


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_REFERENCE_ROOT = (
    _PROJECT_ROOT / "skills" / "contract-type-special-review" / "references"
).resolve()

_RULE_DEFINITIONS: tuple[tuple[ContractTypeCode, str, str], ...] = (
    (ContractTypeCode.SALE, "买卖合同", "ct-01-sale.md"),
    (ContractTypeCode.UTILITY_SUPPLY, "供用电/水/气/热力合同", "ct-02-utility-supply.md"),
    (ContractTypeCode.GIFT, "赠与合同", "ct-03-gift.md"),
    (ContractTypeCode.LOAN, "借款合同", "ct-04-loan.md"),
    (ContractTypeCode.LEASE, "租赁合同", "ct-05-lease.md"),
    (ContractTypeCode.FINANCE_LEASE, "融资租赁合同", "ct-06-finance-lease.md"),
    (ContractTypeCode.WORK_CONTRACT, "承揽合同", "ct-07-work-contract.md"),
    (ContractTypeCode.CONSTRUCTION, "建设工程合同", "ct-08-construction.md"),
    (ContractTypeCode.TRANSPORT, "运输合同", "ct-09-transport.md"),
    (ContractTypeCode.TECHNOLOGY, "技术合同", "ct-10-technology.md"),
    (ContractTypeCode.CUSTODY, "保管合同", "ct-11-custody.md"),
    (ContractTypeCode.WAREHOUSING, "仓储合同", "ct-12-warehousing.md"),
    (ContractTypeCode.ENTRUSTMENT, "委托合同", "ct-13-entrustment.md"),
    (ContractTypeCode.PROPERTY_SERVICE, "物业服务合同", "ct-14-property-service.md"),
    (ContractTypeCode.COMMISSION_AGENCY, "行纪合同", "ct-15-commission-agency.md"),
    (ContractTypeCode.INTERMEDIARY, "中介合同", "ct-16-intermediary.md"),
    (ContractTypeCode.PARTNERSHIP, "合伙合同", "ct-17-partnership.md"),
    (ContractTypeCode.GUARANTEE, "保证合同", "ct-18-guarantee.md"),
    (ContractTypeCode.FACTORING, "保理合同", "ct-19-factoring.md"),
    (ContractTypeCode.EMPLOYMENT, "劳动合同", "ct-20-employment.md"),
    (ContractTypeCode.NDA, "保密协议 / NDA", "ct-21-nda.md"),
    (
        ContractTypeCode.SAAS_SOFTWARE_SERVICE,
        "SaaS / 软件服务协议",
        "ct-22-saas-software-service.md",
    ),
    (ContractTypeCode.EQUITY_TRANSFER, "股权转让协议", "ct-23-equity-transfer.md"),
    (ContractTypeCode.PROCUREMENT_FRAMEWORK, "采购框架协议", "ct-24-procurement-framework.md"),
    (ContractTypeCode.FRANCHISE, "特许经营合同", "ct-25-franchise.md"),
    (
        ContractTypeCode.INVESTMENT_CAPITAL_INCREASE,
        "投资/增资协议",
        "ct-26-investment-capital-increase.md",
    ),
    (
        ContractTypeCode.ASSET_BUSINESS_ACQUISITION,
        "资产/业务收购协议",
        "ct-27-asset-business-acquisition.md",
    ),
    (
        ContractTypeCode.CREDIT_ASSIGNMENT_DEBT_ASSUMPTION,
        "债权转让/债务承担协议",
        "ct-28-credit-assignment-debt-assumption.md",
    ),
    (ContractTypeCode.MORTGAGE_PLEDGE, "抵押/质押合同", "ct-29-mortgage-pledge.md"),
    (ContractTypeCode.IP_LICENSE, "知识产权许可合同", "ct-30-ip-license.md"),
    (ContractTypeCode.INSURANCE, "保险合同", "ct-31-insurance.md"),
    (ContractTypeCode.JOINT_VENTURE, "合资/联营协议", "ct-32-joint-venture.md"),
    (ContractTypeCode.DPA, "数据处理协议（DPA）", "ct-33-dpa.md"),
    (ContractTypeCode.ASSET_CUSTODY, "资产托管合同", "ct-34-asset-custody.md"),
)

CONTRACT_TYPE_RULES: dict[ContractTypeCode, ContractTypeRule] = {
    code: ContractTypeRule(code=code, label=label, path=(_REFERENCE_ROOT / filename).resolve())
    for code, label, filename in _RULE_DEFINITIONS
}


def load_contract_type_rules(
    codes: Sequence[str | ContractTypeCode],
) -> list[LoadedContractTypeRule]:
    """按白名单顺序读取至多三个规则包，重复类型只加载一次。"""

    unique_codes: list[ContractTypeCode] = []
    for raw_code in codes:
        try:
            code = (
                raw_code
                if isinstance(raw_code, ContractTypeCode)
                else ContractTypeCode(raw_code)
            )
        except ValueError as exc:
            raise ContractTypeSkillError(f"未知合同类型：{raw_code}") from exc
        if code not in unique_codes:
            unique_codes.append(code)

    if len(unique_codes) > 3:
        raise ContractTypeSkillError("混合合同最多加载 3 个专项规则包")

    loaded: list[LoadedContractTypeRule] = []
    for code in unique_codes:
        rule = CONTRACT_TYPE_RULES[code]
        if not rule.path.is_relative_to(_REFERENCE_ROOT):
            raise ContractTypeSkillError("专项规则路径不在白名单目录内")
        if not rule.path.is_file():
            raise ContractTypeSkillError(f"专项规则文件不存在：{rule.path.name}")
        loaded.append(
            LoadedContractTypeRule(
                code=code,
                label=rule.label,
                path=rule.path,
                content=rule.path.read_text(encoding="utf-8"),
            )
        )
    return loaded
