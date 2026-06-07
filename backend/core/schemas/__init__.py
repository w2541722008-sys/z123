"""
Pydantic 模型模块 - 集中定义所有 API 请求/响应的数据模型。

按业务域拆分为子模块：
    _auth.py      — 认证（登录、注册、密码重置）
    _chat.py      — 聊天（消息发送、游客、Regenerate/Continue）
    _character.py — 角色（角色操作、配置更新、清空聊天）
    _admin.py     — 管理后台（角色更新、用户管理、订单）
    _story.py     — 剧情（故事线、事件、规则、开场白）
    _memory.py    — 记忆（World Info 条目和分类）
    _base.py      — 共享基类和校验工具函数
"""

from core.schemas._base import _normalize_email  # 向后兼容，router 层使用

from core.schemas._auth import (
    ForgotPasswordPayload,
    LoginPayload,
    RegisterPayload,
    ResetPasswordPayload,
    VerifyCodePayload,
)

from core.schemas._chat import (
    ChatSendPayload,
    ContinuePayload,
    GuestChatPayload,
    GuestMessageItem,
    RegeneratePayload,
)

from core.schemas._character import (
    CharacterActionPayload,
    CharacterProfileUpdatePayload,
    ClearChatPayload,
)

from core.schemas._admin import (
    AdminBatchPlanPayload,
    AdminUpdatePayload,
    AdminUserEditPayload,
    AdminUserPlanUpdatePayload,
    BillingCreateOrderPayload,
)

from core.schemas._story import (
    GreetingPayload,
    KeywordTestPayload,
    PostRulePayload,
    StoryEventPayload,
    StorylinePayload,
)

from core.schemas._memory import (
    MemoryCategoryPayload,
    MemoryEntryPayload,
)
