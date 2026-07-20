# DeepSeek 主模型切换设计

## 目标

将系统默认模型服务切换至 DeepSeek 官方 OpenAI-compatible API，主模型使用
`deepseek-v4-flash`。保留现有 Qwen 模型作为仅在主模型失败时启用的回退，降低
日常模型调用成本而不改变业务编排。

## 范围

- 修改 `Settings` 的默认 LLM 地址和主模型。
- 更新 `.env.example` 的非敏感配置示例。
- 将 `LLM_FALLBACK_MODEL` 设为原主模型 `qwen3.7-plus`。
- 为默认配置与主/回退候选顺序补充自动化测试。

不修改案件分析或合同审查的 Agent、提示词、结构化输出、重试策略和持久化逻辑。

## 配置与数据流

所有调用继续通过 `OpenAICompatibleLLMClient`：

`Settings` -> `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_FALLBACK_MODEL`
-> `OpenAICompatibleLLMClient` -> DeepSeek 主模型 -> Qwen 回退模型（仅主调用失败时）。

默认地址设为 DeepSeek 官方 OpenAI-compatible 地址 `https://api.deepseek.com/v1`，
默认主模型设为 `deepseek-v4-flash`，回退模型设为 `qwen3.7-plus`。部署者可按本地
Qwen 网关或兼容服务覆盖回退模型。真实 API Key 只存在于未提交的 `.env` 或进程环境，示例
文件保持空值，日志不得打印密钥。

## 错误处理

客户端已经仅捕获可控的上游异常并尝试下一候选模型；两者均失败时继续返回既有的
受控 LLM 错误，不暴露密钥、请求正文或供应商响应细节。

## 测试

- 断言 `Settings` 默认指向 DeepSeek 地址和 `deepseek-v4-flash`。
- 断言客户端首先尝试主模型，失败后才尝试 Qwen 回退模型。
- 运行相关后端测试和 Ruff 检查。

## 验收标准

- 未覆盖环境变量时，运行时主模型为 `deepseek-v4-flash`。
- 主模型配置或调用失败时，客户端按照既有机制仅尝试一次 Qwen 回退。
- `.env.example` 不包含任何真实凭据。
