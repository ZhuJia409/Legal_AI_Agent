# Legal AI Agent Docker 数据库连接信息

## MySQL

| 项目 | 内容 |
|---|---|
| 管理软件 | DBeaver |
| 主机 | `127.0.0.1` |
| 端口 | `3306` |
| 数据库 | `legal_ai_agent` |
| 用户名 | `legal_agent` |
| 密码 | `change-me-user` |
| 管理员用户 | `root` |
| 管理员密码 | `change-me-root` |

连接方法：

```text
DBeaver -> 新建连接 -> MySQL
Host: 127.0.0.1
Port: 3306
Database: legal_ai_agent
Username: legal_agent
Password: change-me-user
```

## MongoDB

| 项目 | 内容 |
|---|---|
| 管理软件 | MongoDB Compass |
| 连接地址 | `mongodb://127.0.0.1:27017/legal_ai_agent` |
| 用户名 | 无 |
| 密码 | 无 |

连接方法：

```text
MongoDB Compass -> Add new connection
URI: mongodb://127.0.0.1:27017/legal_ai_agent
Name: Legal AI Agent MongoDB
Authentication: None
```

## Milvus

| 项目 | 内容 |
|---|---|
| 管理软件 | Attu |
| Milvus 地址 | `127.0.0.1:19530` |
| 数据库 | `default` |
| 用户名 | 无 |
| 密码 | 无 |
| SSL | 不启用 |

连接方法：

```text
Attu -> 连接 Milvus 服务器
Milvus 地址: 127.0.0.1:19530
Milvus 数据库: default
认证: 不启用 / token 留空
启用 SSL: 不勾选
检查健康状态: 勾选
WebUI API 地址: 留空
```

## MinIO

| 项目 | 内容 |
|---|---|
| 管理软件 | 浏览器 |
| 控制台地址 | `http://127.0.0.1:9001` |
| API 地址 | `127.0.0.1:9000` |
| 用户名 | `minioadmin` |
| 密码 | `minioadmin` |

连接方法：

```text
浏览器打开: http://127.0.0.1:9001
Username: minioadmin
Password: minioadmin
```

## Redis

| 项目 | 内容 |
|---|---|
| 管理软件 | RedisInsight |
| 连接地址 | `127.0.0.1:6379` |
| 数据库 | `0` |
| 用户名 | 无 |
| 密码 | 无 |

连接方法：

```text
RedisInsight -> Add Redis Database
Host: 127.0.0.1
Port: 6379
Database: 0
Username: 空
Password: 空
```

## Neo4j

| 项目 | 内容 |
|---|---|
| 管理软件 | 浏览器 |
| Browser 地址 | `http://127.0.0.1:7474` |
| Bolt 地址 | `bolt://127.0.0.1:7687` |
| 用户名 | `neo4j` |
| 密码 | `change-me-neo4j` |

连接方法：

```text
浏览器打开: http://127.0.0.1:7474
Connect URL: bolt://127.0.0.1:7687
Username: neo4j
Password: change-me-neo4j
```
