# 基础设施目录

用于存放本地开发和后续部署相关文件，包括 Docker Compose、数据库初始化脚本、服务配置、MinIO bucket 配置、Milvus collection 配置、Neo4j 图数据库配置和部署说明。

## 已配置内容

- `docker-compose.yml`：本地开发数据库与对象存储服务配置，包含 MySQL、Redis、MongoDB、Neo4j、MinIO、etcd、Milvus standalone。

## Neo4j 本地入口

- 浏览器控制台：http://localhost:7474
- Bolt 连接地址：`bolt://localhost:7687`
- 默认开发用户：`neo4j`
- 默认开发密码：由 `.env` 中的 `NEO4J_PASSWORD` 配置，示例值为 `change-me-neo4j`

## 常用命令

```powershell
docker compose -f infra/docker-compose.yml config
docker compose -f infra/docker-compose.yml up -d
docker compose -f infra/docker-compose.yml down
```

首次运行 Docker Desktop 可能需要你手动登录、开启 WSL2/虚拟化或重启系统。
