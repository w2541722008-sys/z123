---
name: git-guardrails
description: 安全护栏 — 自动拦截危险的 git 命令、数据库操作和文件系统操作。通过 PreToolUse hook 在命令执行前进行检查，阻止不可逆的破坏性操作。已拦截：git push、git reset --hard、git clean -f、git branch -D、git checkout .、git restore .、DROP TABLE、DROP DATABASE、无 WHERE 的 DELETE、TRUNCATE、rm -rf 危险路径。支持通过编辑 scripts/block-dangerous-git.sh 自定义拦截规则。
---

# Git 安全护栏

## 概述

本护栏通过 Claude Code 的 PreToolUse hook 机制，在每条 Bash 命令执行前进行安全检查。如果匹配到危险模式，命令被拦截并通过中文消息告知原因和安全替代方案。

## 已拦截的操作

### Git 危险命令
| 命令 | 原因 | 安全替代 |
|------|------|----------|
| `git push` | 推送不可逆 | 手动在终端执行 |
| `git reset --hard` | 不可逆丢失本地修改 | `git stash` |
| `git clean -f` / `git clean -fd` | 删除未追踪文件 | 手动在终端确认 |
| `git branch -D` | 强制删分支 | `git branch -d` |
| `git checkout .` | 丢弃所有未暂存修改 | `git stash` |
| `git restore .` | 丢弃所有未暂存修改 | `git stash` |

### 数据库危险命令
| 命令 | 原因 |
|------|------|
| `DROP TABLE` | 不可逆删除表及数据 |
| `DROP DATABASE` | 不可逆删除整个数据库 |
| `DELETE FROM` 无 `WHERE` | 清空整张表 |
| `TRUNCATE` | 清空表且不可回滚 |

### 文件系统危险命令
| 命令 | 原因 |
|------|------|
| `rm -rf /` 或绝对路径 | 极度危险 |
| `rm -rf .` | 删除当前目录所有内容 |

## 自定义规则

编辑 `scripts/block-dangerous-git.sh`，在对应区块添加新的 grep 模式：

```bash
# 添加新规则示例：
if echo "$COMMAND" | grep -qE '\byour-dangerous-pattern\b'; then
    echo "⛔ 安全护栏拦截：你的拦截原因。"
    exit 2
fi
```

- `exit 0` — 放行
- `exit 2` — 拦截并显示消息

## 实现文件

- Hook 配置：`.claude/settings.local.json` → `hooks.PreToolUse`
- 拦截脚本：`scripts/block-dangerous-git.sh`
