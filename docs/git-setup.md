# Git 环境配置说明

本文档记录本项目推荐的 Git 初始化、身份配置和 GitHub 远程仓库配置方式。

## 当前状态

已通过 `winget` 安装 Git for Windows，并将当前项目初始化为 Git 仓库：

- Git 版本：`2.55.0.windows.2`
- 当前分支：`main`
- 本项目已启用 Git Credential Manager：`credential.helper=manager`
- 本项目换行策略：`core.autocrlf=false`、`core.eol=lf`

注意：当前项目尚未配置提交作者 `user.name` 和 `user.email`，也尚未配置 GitHub 远程仓库地址。

项目已补充以下 Git 项目级配置文件：

- `.gitignore`：忽略依赖、缓存、日志、密钥、本地数据库数据、IDE 配置和 agent 本地状态。
- `.gitattributes`：统一文本文件换行为 LF，并标记常见二进制文件类型。

## 初始化仓库记录

本项目已执行：

```powershell
git init -b main
```

## 配置提交身份

只对当前仓库生效：

```powershell
git config user.name "你的 GitHub 用户名"
git config user.email "你的邮箱"
```

如果希望对本机所有仓库生效：

```powershell
git config --global user.name "你的 GitHub 用户名"
git config --global user.email "你的邮箱"
```

## 配置远程仓库

创建 GitHub 仓库后，在项目根目录配置远程地址：

```powershell
git remote add origin https://github.com/<owner>/<repo>.git
```

检查远程地址：

```powershell
git remote -v
```

## 首次提交

配置提交身份和远程仓库后，再执行首次提交：

```powershell
git add .
git commit -m "chore: initialize project structure"
git push -u origin main
```

## GitHub Token 安全建议

不要把 GitHub Personal Access Token 写入：

- 远程仓库 URL
- `.env`
- `.git/config`
- README 或任何项目文件
- 终端历史中会被保存的脚本

推荐方式：

```powershell
gh auth login
```

如果使用 HTTPS 推送，Git 弹出凭据输入时再粘贴新生成的 token。凭据应由 Git Credential Manager 或系统凭据管理器保存。

如果 token 曾经出现在聊天、日志或文件中，建议立即在 GitHub 撤销并重新生成。
