# 案件分析并联智能体设计

## 目标

将现有单次模型调用升级为可审计的案件分析并联流程。首版以同步请求跑通完整分析闭环，只基于用户上传材料形成中立、条件化的分析结果；材料不足时明确标记待补充，不把模型输出包装成确定法律结论。

## 架构

主流程使用 LangGraph `StateGraph` 固定编排，专业分析节点使用 LangChain `create_agent()` 和严格 Pydantic 结构化输出。所有并行节点只读同一份冻结输入快照，不相互修改结论，由后续汇总节点统一消歧。

```text
prepare_input
  -> [intake_screening | fact_reconstruction | deadline_scan]
  -> fact_reconstruction -> [evidence_review | legal_classification]
  -> identify_issues
  -> Send(issue_worker, 最多 5 个争议焦点)
  -> Send(risk_worker, 己方/对方/执行成本)
  -> Send(strategy_worker, 激进/稳健/保守)
  -> build_report
```

`build_report` 只按已校验的阶段结果确定性汇总，不再调用模型重写事实。第八阶段只生成案件分析报告草稿，不生成可直接提交法院的诉状；第九阶段只识别期限线索，缺少触发日期时不得计算截止日。

## 证据与输出边界

- 输入材料按段落生成稳定 ID；模型只能返回段落 ID，不能自行复制或生成引用。
- 服务端校验段落 ID 后回填原文摘录；未知 ID 导致对应模型输出校验失败。
- 模型不得编造法条、案例、证据、客户立场或程序日期。
- 未明确代理方时固定采用中立分析，不输出精确胜诉概率。
- 每个阶段包含执行状态、缺失信息、错误信息和 `requires_human_review=true`。
- 基础事实、法律分类或全部争议焦点失败时返回受控错误；非关键分支失败时返回 `partial` 报告。

## 首版范围

- 保留同步 `POST /api/v1/case-analyses`。
- 案件分析支持 PDF、DOCX、MD、TXT；合同审查仍只支持 PDF、DOCX。
- 默认最大正文 60,000 字符、文件 20 MiB、模型并发 4、争议焦点 5、单次模型超时 120 秒。
- 不接入 RAG、Milvus、reranker、联网检索、DeepAgents、LangGraph checkpointer、HITL、数据库持久化或 PDF 报告生成；PDF 仍是支持的输入格式。
- 所有输出固定包含专业法律人士复核提示。

## 前端

现有法律分析工作台增加案件分析专用结果组件，展示总览、九阶段状态、时间线、证据缺口、法律关系、争议焦点、风险、三套方案、期限信息、来源引用和报告限制。页面沿用既有视觉语言，明确区分 `succeeded`、`needs_input`、`failed`、`skipped` 和整体 `partial` 状态。

## 验收

使用 `docx/test_case.md` 跑真实模型与网页上传流程。合理结果应为 `partial`：能够识别婚约财产纠纷及核心争点，同时把证据三性、代理立场、程序期限、执行和成本信息标记为待补充，不生成无来源的法律结论。
