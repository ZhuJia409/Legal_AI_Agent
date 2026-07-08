# 后端目录

用于存放 FastAPI 后端服务相关文件，包括 API 路由、业务服务、数据模型、数据库访问、智能体编排、RAG 检索服务、配置管理和后端测试辅助代码。

## 已配置内容

- `pyproject.toml`：后端依赖和测试/格式工具配置。
- `app/main.py`：FastAPI 应用入口。
- `app/api/health.py`：健康检查接口。
- `app/core/config.py`：环境变量配置。
- `tests/test_health.py`：后端基础健康检查测试。

## 常用命令

```powershell
uv sync
uv run pytest
uv run uvicorn app.main:app --reload
```
