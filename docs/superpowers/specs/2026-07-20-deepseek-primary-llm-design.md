# DeepSeek 主模型切换设计

## 目标

将系统默认模型服务切换至 DeepSeek 官方 OpenAI-compatible API，模型使用
`deepseek-v4-flash`，不配置跨供应商回退模型。此方式降低日常模型调用成本且不改变
业务编排。

## 范围

- 修改 `Settings` 的默认 LLM 地址和主模型。
- 更新 `.env.example` 的非敏感配置示例。
- 清空 `LLM_FALLBACK_MODEL`，避免将 Qwen 模型名发送至 DeepSeek 官方地址。
- 为默认配置与单模型候选行为补充自动化测试。

不修改案件分析或合同审查的 Agent、提示词、结构化输出、重试策略和持久化逻辑。

## 配置与数据流

所有调用继续通过 `OpenAICompatibleLLMClient`：

`Settings` -> `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`
-> `OpenAICompatibleLLMClient` -> DeepSeek 模型。

默认地址设为 DeepSeek 官方 OpenAI-compatible 地址 `https://api.deepseek.com/v1`，
默认模型设为 `deepseek-v4-flash`，回退模型为空。现有客户端的一次调用只能使用同一个
地址和凭据，因此不把 Qwen 作为跨供应商回退，避免错误请求与非预期成本。真实 API Key 只
存在于未提交的 `.env` 或进程环境，示例
文件保持空值，日志不得打印密钥。

## 错误处理

客户端已经仅捕获可控的上游异常；DeepSeek 调用失败时继续返回既有的受控 LLM 错误，
不暴露密钥、请求正文或供应商响应细节。

## 测试

- 断言 `Settings` 默认指向 DeepSeek 地址和 `deepseek-v4-flash`。
- 断言客户端的候选列表只包含 DeepSeek 模型。
- 运行相关后端测试和 Ruff 检查。

## 验收标准

- 未覆盖环境变量时，运行时主模型为 `deepseek-v4-flash`。
- 模型调用失败时，不会以 Qwen 模型名向 DeepSeek 官方地址发起额外请求。
- `.env.example` 不包含任何真实凭据。
