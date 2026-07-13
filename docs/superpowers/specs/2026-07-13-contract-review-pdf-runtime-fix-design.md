# 合同审查 PDF 运行时与安全日志修复设计

## 背景与根因

合同审查完整 DAG 在 LangSmith 中成功后，FastAPI 继续调用 Tectonic 生成 PDF。Windows 下使用 Uvicorn `--reload` 或多 worker 时，Uvicorn 会选择 `SelectorEventLoop`；该事件循环不支持 `asyncio.create_subprocess_exec`，因此 PDF 编译在启动子进程时立即抛出 `NotImplementedError`。现有 renderer 将该异常包装为 `ReportPdfGenerationError`，API 返回 `500 report_pdf_generation_error`，前端据此显示 PDF 生成失败。

当前错误发生在持久化之前，所以该次任务不会写入 MySQL、MongoDB 或 MinIO。现有日志只记录包装后的异常类型，无法区分子进程启动、超时、退出码异常或输出校验失败。与此同时，`httpx` 的 INFO 请求日志会输出 MinerU 预签名 URL 的完整查询参数，造成签名信息进入本地日志。

## 目标

- Windows `--reload`、Windows 多 worker、Windows 单进程和 Linux 环境均可调用 Tectonic。
- 保持现有 API 状态码与错误码契约不变。
- 保持 Tectonic 仅使用预热缓存，不自动下载二进制或宏包。
- 超时、取消、启动失败和非零退出均有受控行为，不遗留长期运行的子进程或临时合同文件。
- 日志可定位失败阶段，但不记录合同正文、LaTeX 源文、Tectonic 原始 stdout/stderr、预签名查询参数或密钥。
- 不新增数据库迁移，不改变合同背景审查接口行为。

## 方案选择

采用“同步 `subprocess.run` + 工作线程隔离”方案。`TectonicCompiler.compile` 保持异步公开接口，但将完整的临时目录创建、Tectonic 运行、输出读取和清理放在同步函数中，再通过 `asyncio.to_thread` 调用。

没有采用以下替代方案：

- 仅禁用 Uvicorn `--reload`：无法覆盖 Windows 多 worker 和其他启动入口。
- 自定义 Uvicorn Proactor loop factory：把 PDF 能力绑定到服务器实现细节，升级成本高。
- 独立 PDF 队列或服务：当前吞吐和部署规模不需要新增基础设施。

## PDF 编译边界

`TectonicCompiler` 继续使用参数列表启动进程，不开启 shell。同步编译函数负责：

1. 校验 Tectonic 文件存在。
2. 在独立临时目录写入 LaTeX，并将仓库级缓存路径写入子进程环境变量。
3. 使用 `--only-cached`、固定输出目录和固定输入文件名调用 Tectonic。
4. 使用 `subprocess.run` 的 timeout 强制终止并回收超时进程。
5. 丢弃 stdout/stderr；Tectonic 的临时日志只存在于临时目录并随调用清理。
6. 校验退出码、PDF 文件存在性、非空内容和 `%PDF-` 文件头。

异步调用被取消时，线程中的编译仍由固定 timeout 约束，临时目录由同步函数持有，避免事件循环取消后提前删除仍被子进程使用的文件。最长残留时间不超过 `tectonic_timeout_seconds`。

## 错误模型与 API 映射

扩展受控 PDF 异常，使其携带安全诊断字段：

- `failure_stage`：`renderer_unavailable`、`process_start`、`compile_timeout`、`compile_exit`、`output_validation` 或 `template_render`。
- `cause_type`：底层异常类名；没有底层异常时为空。
- `return_code`：仅在 Tectonic 非零退出时提供。

字段不包含异常原文、命令输出、LaTeX 或合同数据。

API 映射保持不变：

- Tectonic 文件不存在或无法启动：`503 pdf_renderer_unavailable`。
- 模板、超时、非零退出或输出校验失败：`500 report_pdf_generation_error`。

API 日志记录 `task_id`、安全诊断字段和包装异常类型，不记录原始 stderr。前端现有错误显示逻辑无需改变。

## HTTP 日志脱敏

新增通用日志 Filter，对日志记录中的 HTTP(S) URL 进行查询参数和 fragment 移除。Filter 在格式化前处理字符串消息和参数，确保 `httpx` 使用参数化日志时同样生效；方法、scheme、host、port、path 和响应状态保留。

Filter 挂载到应用日志配置中的 handler，使 `httpx`、`httpcore` 以及其他经过同一 handler 的预签名 URL 都受保护。Filter 发生解析异常时采用保守降级：删除 `?` 或 `#` 之后的内容，不抛出日志处理异常。

不通过简单关闭全部 `httpx` INFO 日志解决，因为开发环境仍需要请求方法、目标服务路径和状态码进行排障。

## 测试设计

### PDF 编译测试

- 在 Windows Selector 事件循环或等效“不允许 asyncio 子进程”的条件下成功生成 PDF，证明实现不再调用 `asyncio.create_subprocess_exec`。
- 参数列表包含 `--only-cached`，不启用 shell。
- Tectonic 缺失和启动失败映射到 `PdfRendererUnavailableError`。
- timeout 映射到 `ReportPdfGenerationError`，且失败阶段为 `compile_timeout`。
- 非零退出码只暴露 return code，不暴露 stderr。
- 输出缺失、空文件和非法 PDF 头映射为 `output_validation`。

### API 与日志测试

- API 针对安全诊断字段写入结构化日志，公开响应仍保持原错误码和文案。
- 带 `OSSAccessKeyId`、`Signature`、token 或任意查询参数的 URL 经 Filter 后不包含查询参数。
- 不带查询参数的 URL、普通日志参数和异常日志保持可读。
- 现有 complete、partial、下载与合同背景审查测试保持通过。

### 验收

- `uv run ruff check .`
- `uv run pytest`
- Windows 本地 `--reload` 启动后，使用现有 LangSmith 结构化输出或测试合同验证 PDF 可生成并持久化。
- 检查日志中不存在预签名查询参数、合同正文、LaTeX 或 Tectonic stderr。
- `git status --short` 只包含本次修复和用户原有未跟踪内容。

## 非目标

- 不从 LangSmith 自动恢复历史失败任务。
- 不为 PDF 增加队列、重试、数据库状态迁移或前端内嵌预览。
- 不改变合同审查 DAG、模型提示词、报告模板内容或法律免责声明。
