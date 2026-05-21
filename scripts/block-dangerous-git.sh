#!/usr/bin/env bash
# Git + DB 安全护栏 — 拦截不可逆的危险命令
# 来源：改编自 mattpocock/skills (git-guardrails-claude-code)
# 扩展：增加数据库危险操作和文件系统危险操作

set -euo pipefail

# 从 stdin 读取 Claude Code 传入的工具调用 JSON
INPUT=$(cat)

# 提取 Bash 命令（支持新旧两种 JSON 结构）
COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
# tool_use 格式：{tool_name: 'Bash', tool_input: {command: '...'}}
if 'tool_input' in data:
    cmd = data['tool_input'].get('command', '')
else:
    cmd = data.get('command', '')
print(cmd)
" 2>/dev/null || echo "")

# 如果没有提取到命令，放行（非 Bash 工具调用）
if [ -z "$COMMAND" ]; then
    exit 0
fi

# ============================================================
# 危险命令模式匹配
# ============================================================

# --- Git 危险操作 ---
if echo "$COMMAND" | grep -qE '\bgit reset --hard\b'; then
    echo "⛔ 安全护栏拦截：git reset --hard 会不可逆地丢失本地修改。"
    echo "   请改用 git stash 或手动确认后到终端执行。"
    exit 2
fi

if echo "$COMMAND" | grep -qE '\bgit clean -f'; then
    echo "⛔ 安全护栏拦截：git clean -f 会删除未追踪的文件，不可恢复。"
    echo "   如需清理，请手动在终端执行。"
    exit 2
fi

if echo "$COMMAND" | grep -qE '\bgit branch -D\b'; then
    echo "⛔ 安全护栏拦截：git branch -D 会强制删除分支，不可恢复。"
    echo "   请改用 git branch -d（安全删除，仅删除已合并分支）。"
    exit 2
fi

if echo "$COMMAND" | grep -qE '\bgit checkout \.'; then
    echo "⛔ 安全护栏拦截：git checkout . 会丢弃所有未暂存的修改。"
    echo "   请使用 git stash 暂存修改，或手动在终端确认执行。"
    exit 2
fi

if echo "$COMMAND" | grep -qE '\bgit restore \.'; then
    echo "⛔ 安全护栏拦截：git restore . 会丢弃所有未暂存的修改。"
    echo "   请使用 git stash 暂存修改。"
    exit 2
fi

# --- 数据库危险操作 ---
if echo "$COMMAND" | grep -qE '\bDROP TABLE\b'; then
    echo "⛔ 安全护栏拦截：DROP TABLE 会不可逆地删除数据库表及所有数据。"
    echo "   如需执行，请手动在数据库管理工具中操作，并确认有备份。"
    exit 2
fi

if echo "$COMMAND" | grep -qE '\bDROP DATABASE\b'; then
    echo "⛔ 安全护栏拦截：DROP DATABASE 会删除整个数据库。"
    echo "   此操作不可逆，请手动确认后执行。"
    exit 2
fi

if echo "$COMMAND" | grep -qE '\bDELETE FROM\b' && ! echo "$COMMAND" | grep -qE '\bWHERE\b'; then
    echo "⛔ 安全护栏拦截：DELETE FROM 缺少 WHERE 条件，会清空整张表。"
    echo "   请添加 WHERE 条件限定删除范围，或手动在终端确认。"
    exit 2
fi

if echo "$COMMAND" | grep -qE '\bTRUNCATE\b'; then
    echo "⛔ 安全护栏拦截：TRUNCATE 会清空表数据且不可回滚。"
    echo "   请手动确认后执行。"
    exit 2
fi

# --- 文件系统危险操作 ---
if echo "$COMMAND" | grep -qE '\brm -rf\s+/'; then
    echo "⛔ 安全护栏拦截：rm -rf 作用于根路径或绝对路径，极度危险。"
    echo "   请确认路径后手动执行。"
    exit 2
fi

if echo "$COMMAND" | grep -qE '\brm -rf\s+\.\b'; then
    echo "⛔ 安全护栏拦截：rm -rf . 会删除当前目录所有内容。"
    echo "   如需清理，请指定具体目录。"
    exit 2
fi

# 所有检查通过，放行
exit 0
