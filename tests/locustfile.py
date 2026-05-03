"""
AIFriend 压力测试脚本 (locust)

安装：pip install locust
运行：locust -f locustfile.py --host=https://lunawhisp.com
      本地：locust -f locustfile.py --host=http://localhost:8000

访问 http://localhost:8089 查看 Locust Web UI
"""

from __future__ import annotations

import json
import random
from locust import HttpUser, task, between, tag


# ============================================================
# 测试用户池（替换为实际测试账号）
# ============================================================
TEST_USERS = [
    {"email": "test1@example.com", "password": "TestPass123!"},
    {"email": "test2@example.com", "password": "TestPass123!"},
    {"email": "test3@example.com", "password": "TestPass123!"},
]

# 游客可访问的角色ID（替换为实际角色ID）
CHARACTER_IDS = ["1", "2", "3"]


class AIFriendUser(HttpUser):
    """模拟已登录用户的完整行为。"""

    wait_time = between(3, 8)  # 模拟用户思考时间
    host = "http://localhost:8000"

    def on_start(self):
        """登录获取 token。"""
        user = random.choice(TEST_USERS)
        resp = self.client.post(
            "/api/auth/login",
            json={"email": user["email"], "password": user["password"]},
            name="/api/auth/login",
        )
        if resp.status_code == 200:
            data = resp.json()
            self.token = data.get("token", "")
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.token = ""
            self.headers = {}

    @task(5)
    @tag("chat")
    def chat_send(self):
        """发送聊天消息（同步模式）。"""
        if not self.token:
            return
        char_id = random.choice(CHARACTER_IDS)
        messages = [
            "你好呀", "今天心情怎么样？", "给我讲个故事吧",
            "你觉得什么是真正的友谊？", "最近有什么有趣的事吗？",
        ]
        self.client.post(
            "/api/chat/send",
            json={"character_id": char_id, "message": random.choice(messages)},
            headers=self.headers,
            name="/api/chat/send",
            timeout=30,
        )

    @task(3)
    @tag("chat")
    def chat_stream(self):
        """流式聊天（SSE）。"""
        if not self.token:
            return
        char_id = random.choice(CHARACTER_IDS)
        messages = ["嗯嗯", "然后呢？", "继续说", "好的"]
        with self.client.post(
            "/api/chat/stream",
            json={"character_id": char_id, "message": random.choice(messages)},
            headers=self.headers,
            name="/api/chat/stream",
            stream=True,
            timeout=30,
        ) as resp:
            # 消费 SSE 流，避免连接堆积
            for _ in resp.iter_lines():
                pass

    @task(2)
    @tag("read")
    def get_characters(self):
        """获取角色列表。"""
        self.client.get(
            "/api/characters",
            headers=self.headers,
            name="/api/characters",
        )

    @task(1)
    @tag("read")
    def get_me(self):
        """获取当前用户信息。"""
        if not self.token:
            return
        self.client.get(
            "/api/auth/me",
            headers=self.headers,
            name="/api/auth/me",
        )


class AIFriendGuest(HttpUser):
    """模拟游客行为。"""

    wait_time = between(5, 15)
    host = "http://localhost:8000"

    @task(5)
    @tag("guest")
    def guest_stream(self):
        """游客试聊。"""
        char_id = random.choice(CHARACTER_IDS)
        messages = ["你好", "介绍一下你自己", "你好呀"]
        with self.client.post(
            "/api/chat/guest-stream",
            json={"character_id": char_id, "message": random.choice(messages)},
            name="/api/chat/guest-stream",
            stream=True,
            timeout=30,
        ) as resp:
            for _ in resp.iter_lines():
                pass

    @task(2)
    @tag("read")
    def get_plans(self):
        """查看会员套餐。"""
        self.client.get("/api/billing/plans", name="/api/billing/plans")


class AIFriendHealthCheck(HttpUser):
    """只做健康检查，用于验证服务稳定性。"""

    wait_time = between(1, 3)
    host = "http://localhost:8000"

    @task
    def health(self):
        self.client.get("/api/health", name="/api/health")
