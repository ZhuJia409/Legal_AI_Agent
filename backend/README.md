# 后端

`backend/` 是 Legal AI Agent 的 FastAPI 服务，负责案件分析、合同审查、MinerU 文档解析、结构化 Agent 工作流、历史持久化和 PDF 生成。

## 目录

| 路径 | 说明 |
| --- | --- |
| [`app/`](app/README.md) | 应用入口、API、schema、服务、Agent 图、仓储和外部集成。 |
| `alembic/` | MySQL 结构迁移。 |
| `tests/` | 后端单元、服务和 API 测试。 |
| `pyproject.toml` | Python 3.12 依赖及 Ruff、pytest 配置。 |
| `alembic.ini` | Alembic 配置。 |

## 初始化与迁移

```powershell
cd backend
uv sync
uv run alembic upgrade head
```

数据库结构只通过 Alembic 管理，应用启动时不会自动建表。

## 启动

```powershell
cd backend
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

模型、MinerU、MySQL、MongoDB、MinIO 和 Tectonic 配置从仓库根目录 `.env` 读取。缺少配置时，运行时返回受控错误，不使用 mock fallback。

## 检查

```powershell
cd backend
uv run ruff check .
uv run pytest
```

详细分层和调用链见 [`app/README.md`](app/README.md)。
