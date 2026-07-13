# 脚本目录

用于存放项目辅助脚本，包括环境检查、数据导入、数据库迁移辅助、向量索引初始化、文档批处理、服务启动和维护脚本。

合同审查 PDF 依赖本地 Tectonic。请在仓库根目录运行 `powershell -ExecutionPolicy Bypass -File scripts/setup-tectonic.ps1`；脚本会校验固定版本发布包、完成中文模板缓存预热并执行离线复编译校验，运行时仅使用已预热缓存，不会自动下载编译器或宏包。
