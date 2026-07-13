---
name: contract-type-special-review
description: Use when 合同审查智能体需要依据已确认的中国法合同类型，加载对应专项规则并识别类型特有风险；适用于买卖、租赁、建设工程、技术合同、股权转让、SaaS、数据处理协议等场景。
---

# 合同类型专项审查

## 使用方式

在实质审查阶段，根据主智能体传入的合同类型候选、合同结构、条款文本、背景画像、主体画像和形式结构画像，判断应加载的专项规则包。

你只负责合同类型专项审查，不替代主体资格审查、形式结构审查、通用效力审查、核心条款审查和报告生成。

## 执行流程

1. 识别主合同类型。
2. 判断是否为混合合同。
3. 单一类型加载 1 个规则包。
4. 混合合同加载 2-3 个相关规则包。
5. 按已加载规则包执行专项审查。
6. 合并重复风险，按统一格式输出给主智能体。

## 规则包加载

- 买卖合同：读取 `references/ct-01-sale.md`
- 供用电/水/气/热力合同：读取 `references/ct-02-utility-supply.md`
- 赠与合同：读取 `references/ct-03-gift.md`
- 借款合同：读取 `references/ct-04-loan.md`
- 租赁合同：读取 `references/ct-05-lease.md`
- 融资租赁合同：读取 `references/ct-06-finance-lease.md`
- 承揽合同：读取 `references/ct-07-work-contract.md`
- 建设工程合同：读取 `references/ct-08-construction.md`
- 运输合同：读取 `references/ct-09-transport.md`
- 技术合同：读取 `references/ct-10-technology.md`
- 保管合同：读取 `references/ct-11-custody.md`
- 仓储合同：读取 `references/ct-12-warehousing.md`
- 委托合同：读取 `references/ct-13-entrustment.md`
- 物业服务合同：读取 `references/ct-14-property-service.md`
- 行纪合同：读取 `references/ct-15-commission-agency.md`
- 中介合同：读取 `references/ct-16-intermediary.md`
- 合伙合同：读取 `references/ct-17-partnership.md`
- 保证合同：读取 `references/ct-18-guarantee.md`
- 保理合同：读取 `references/ct-19-factoring.md`
- 劳动合同：读取 `references/ct-20-employment.md`
- 保密协议 / NDA：读取 `references/ct-21-nda.md`
- SaaS / 软件服务协议：读取 `references/ct-22-saas-software-service.md`
- 股权转让协议：读取 `references/ct-23-equity-transfer.md`
- 采购框架协议：读取 `references/ct-24-procurement-framework.md`
- 特许经营合同：读取 `references/ct-25-franchise.md`
- 投资/增资协议：读取 `references/ct-26-investment-capital-increase.md`
- 资产/业务收购协议：读取 `references/ct-27-asset-business-acquisition.md`
- 债权转让/债务承担协议：读取 `references/ct-28-credit-assignment-debt-assumption.md`
- 抵押/质押合同：读取 `references/ct-29-mortgage-pledge.md`
- 知识产权许可合同：读取 `references/ct-30-ip-license.md`
- 保险合同：读取 `references/ct-31-insurance.md`
- 合资/联营协议：读取 `references/ct-32-joint-venture.md`
- 数据处理协议（DPA）：读取 `references/ct-33-dpa.md`
- 资产托管合同：读取 `references/ct-34-asset-custody.md`

## 输出格式

每个风险项按以下字段输出：

```json
{
  "risk_level": "fatal | high | medium | low",
  "contract_location": "页码/条款号/可定位片段",
  "issue": "问题描述",
  "basis": "审查依据",
  "impact": "影响后果",
  "suggestion": "修改建议",
  "negotiation_strategy": "谈判策略",
  "paragraph_ids": ["p0001"]
}
```

只引用输入证据中真实存在的 `paragraph_ids`。服务端负责校验段落编号，并统一补充
`finding_id`、`module`、`source_refs` 和 `requires_human_review=true`；专项 Agent 不得自行
伪造这些字段。规则包仅作为审查提示，不得输出确定法律结论，所有风险均须由专业法律人士复核。
