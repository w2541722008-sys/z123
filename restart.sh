#!/bin/bash

# AI Friend 一键重启脚本
# 用法: ./restart.sh [frontend|backend|all]
# 默认重启后端（因为前端通常是静态文件，不需要频繁重启）

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目路径
PROJECT_DIR="/Users/jjj/aifriend"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}     AI Friend 一键重启工具${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 检查参数
TARGET="${1:-backend}"  # 默认重启后端

if [[ "$TARGET" != "frontend" && "$TARGET" != "backend" && "$TARGET" != "all" ]]; then
    echo -e "${RED}错误: 参数只能是 frontend、backend 或 all${NC}"
    echo "用法: ./restart.sh [frontend|backend|all]"
    echo "  - backend: 只重启后端（默认）"
    echo "  - frontend: 只重启前端"
    echo "  - all: 重启前后端"
    exit 1
fi

# 函数：查找并杀死进程
kill_process() {
    local pattern="$1"
    local name="$2"
    
    # 查找进程
    pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    
    if [ -n "$pids" ]; then
        echo -e "${YELLOW}发现正在运行的 $name 进程，准备停止...${NC}"
        for pid in $pids; do
            echo "  停止进程 PID: $pid"
            kill -TERM "$pid" 2>/dev/null || true
        done
        
        # 等待进程结束
        sleep 2
        
        # 强制杀死还没结束的
        pids=$(pgrep -f "$pattern" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            echo -e "${YELLOW}强制停止残留进程...${NC}"
            for pid in $pids; do
                kill -KILL "$pid" 2>/dev/null || true
            done
        fi
        
        echo -e "${GREEN}✓ $name 已停止${NC}"
    else
        echo -e "${GREEN}✓ $name 没有在运行${NC}"
    fi
}

# 函数：重启后端
restart_backend() {
    echo ""
    echo -e "${BLUE}>>> 重启后端服务${NC}"
    echo "========================================"
    
    # 停止现有后端进程
    kill_process "uvicorn main:app" "后端服务"
    
    # 检查 Python 环境
    if [ ! -d "$BACKEND_DIR/venv" ]; then
        echo -e "${YELLOW}虚拟环境不存在，正在创建...${NC}"
        cd "$BACKEND_DIR"
        python3 -m venv venv
        source venv/bin/activate
        pip install -r requirements.txt -q
    else
        source "$BACKEND_DIR/venv/bin/activate"
    fi
    
    # 加载环境变量
    if [ -f "$BACKEND_DIR/.env" ]; then
        echo -e "${GREEN}✓ 加载环境变量${NC}"
        export $(grep -v '^#' "$BACKEND_DIR/.env" | xargs)
    fi
    
    # 启动后端（后台运行）
    echo ""
    echo -e "${YELLOW}正在启动后端服务...${NC}"
    cd "$BACKEND_DIR"
    nohup python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload > backend.log 2>&1 &
    
    # 等待启动
    sleep 3
    
    # 检查是否启动成功
    if pgrep -f "uvicorn main:app" > /dev/null; then
        echo -e "${GREEN}✓ 后端服务启动成功！${NC}"
        echo -e "  访问地址: http://localhost:8000"
        echo -e "  日志文件: $BACKEND_DIR/backend.log"
    else
        echo -e "${RED}✗ 后端服务启动失败，请检查日志${NC}"
        echo "  日志: $BACKEND_DIR/backend.log"
        tail -20 "$BACKEND_DIR/backend.log"
        exit 1
    fi
}

# 函数：重启前端
restart_frontend() {
    echo ""
    echo -e "${BLUE}>>> 重启前端服务${NC}"
    echo "========================================"
    
    # 停止现有前端进程（如果使用 http-server）
    kill_process "http-server" "前端服务"
    
    # 检查是否有 http-server
    if ! command -v npx &> /dev/null; then
        echo -e "${YELLOW}警告: npx 未安装，跳过前端启动${NC}"
        echo "  前端是静态文件，可以直接用浏览器打开:"
        echo "  file://$FRONTEND_DIR/index.html"
        return
    fi
    
    # 启动前端（后台运行）
    echo -e "${YELLOW}正在启动前端服务...${NC}"
    cd "$FRONTEND_DIR"
    nohup npx http-server -p 8080 -c-1 > frontend.log 2>&1 &
    
    sleep 2
    
    if pgrep -f "http-server" > /dev/null; then
        echo -e "${GREEN}✓ 前端服务启动成功！${NC}"
        echo -e "  访问地址: http://localhost:8080"
        echo -e "  日志文件: $FRONTEND_DIR/frontend.log"
    else
        echo -e "${YELLOW}警告: 前端服务启动失败${NC}"
        echo "  前端是静态文件，可以直接用浏览器打开:"
        echo "  file://$FRONTEND_DIR/index.html"
    fi
}

# 函数：显示状态
show_status() {
    echo ""
    echo -e "${BLUE}>>> 服务状态${NC}"
    echo "========================================"
    
    # 检查后端
    if pgrep -f "uvicorn main:app" > /dev/null; then
        backend_pid=$(pgrep -f "uvicorn main:app" | head -1)
        echo -e "${GREEN}● 后端运行中${NC} (PID: $backend_pid)"
        echo "  http://localhost:8000"
    else
        echo -e "${RED}○ 后端未运行${NC}"
    fi
    
    # 检查前端
    if pgrep -f "http-server" > /dev/null; then
        frontend_pid=$(pgrep -f "http-server" | head -1)
        echo -e "${GREEN}● 前端运行中${NC} (PID: $frontend_pid)"
        echo "  http://localhost:8080"
    else
        echo -e "${YELLOW}○ 前端未运行${NC} (静态文件可直接打开)"
    fi
}

# 主逻辑
case "$TARGET" in
    backend)
        restart_backend
        ;;
    frontend)
        restart_frontend
        ;;
    all)
        restart_backend
        restart_frontend
        ;;
esac

# 显示最终状态
show_status

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}         重启完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "常用地址:"
echo "  管理后台: http://localhost:8000/admin.html"
echo "  API文档:  http://localhost:8000/docs"
echo ""
echo "查看日志:"
echo "  后端: tail -f $BACKEND_DIR/backend.log"
echo "  前端: tail -f $FRONTEND_DIR/frontend.log"
echo ""
