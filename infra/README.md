# 基础设施目录

用于存放本地开发和后续部署相关文件，包括 Docker Compose、数据库初始化脚本、服务配置、MinIO bucket 配置、Milvus collection 配置和部署说明。

## 已配置内容

- `docker-compose.yml`：本地开发数据库与对象存储服务配置，包含 MySQL、Redis、MongoDB、MinIO、etcd、Milvus standalone。

## 常用命令

```powershell
docker compose -f infra/docker-compose.yml config
docker compose -f infra/docker-compose.yml up -d
docker compose -f infra/docker-compose.yml down
```

首次运行 Docker Desktop 可能需要你手动登录、开启 WSL2/虚拟化或重启系统。
