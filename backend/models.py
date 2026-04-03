"""
Pydantic 模型模块 - 集中定义所有 API 请求/响应的数据模型

这个文件存放：
- 所有请求体（Payload）的校验规则
- 数据字段的类型约束和默认值
- 字段验证规则（长度限制、必填/可选等）

使用 Pydantic 的好处：
- 自动校验请求数据，不符合规则时返回 422 错误
- 自动生成 API 文档
- 类型安全，IDE 有代码提示
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ============================================================
# 认证相关模型
# ============================================================
class LoginPayload(BaseModel):
    """登录接口请求体。"""
    email: str
    password: str = Field(min_length=6, max_length=64)


class RegisterPayload(BaseModel):
    """
    注册接口的请求体。

    nickname 是可选的，不填时用邮箱前缀代替（比如 hello@example.com → hello）。
    """
    email: str
    password: str = Field(min_length=6, max_length=64)
    nickname: str = Field(default="", max_length=20)


# ============================================================
# 角色相关模型
# ============================================================
class CharacterProfileUpdatePayload(BaseModel):
    """更新用户对某个角色的个性化配置。"""
    character_id: str
    remark: str = Field(default="", max_length=40)
    custom_signature: str = Field(default="", max_length=100)


class CharacterActionPayload(BaseModel):
    """角色相关操作的通用请求体（只传角色 ID）。"""
    character_id: str


class ClearChatPayload(BaseModel):
    """
    清空聊天并重新选择剧情线入口。

    greeting_index：
      - None / -1 → 使用角色默认开场白（first_mes）
      - 0          → 同上（0 号即 first_mes）
      - 1, 2, …   → alternate_greetings 列表下标（从 1 起算，与前端展示序号一致）
    """
    character_id: str
    greeting_index: int = Field(default=-1)  # -1 表示使用默认


# ============================================================
# 聊天相关模型
# ============================================================
class ChatSendPayload(BaseModel):
    """发送聊天消息的请求体。"""
    character_id: str
    message: str = Field(min_length=1, max_length=2000)


class GuestMessageItem(BaseModel):
    """
    游客前端临时历史消息条目（不存库，仅用于单次上下文）。
    
    role: 'user' | 'assistant'
    content: 消息内容
    """
    role: str
    content: str = Field(max_length=2000)


class GuestChatPayload(BaseModel):
    """
    游客试聊接口请求体。不需要 token，不存消息，只做一次 AI 调用。
    
    guest_history: 最多传 10 条前端临时历史，让 AI 保留上下文
    """
    character_id: str
    message: str = Field(min_length=1, max_length=500)
    guest_history: list[GuestMessageItem] = Field(default_factory=list, max_length=10)


# ============================================================
# 管理后台模型
# ============================================================
class AdminUpdatePayload(BaseModel):
    """
    管理后台更新角色请求体。
    
    updates: {字段名: 新值}
    支持 rl__XXX 前缀写回 runtime_layers。
    """
    updates: dict[str, Any]


class AdminUserPlanUpdatePayload(BaseModel):
    """管理后台手动调整用户会员档位。"""
    plan_type: str = Field(pattern="^(free|vip|svip)$")
    duration_days: int = Field(default=30, ge=1, le=3650)


class AdminUserEditPayload(BaseModel):
    """管理后台编辑用户信息。"""
    email: str | None = Field(default=None, max_length=255)
    nickname: str | None = Field(default=None, max_length=20)


class AdminBatchPlanPayload(BaseModel):
    """管理后台批量调整用户档位。"""
    user_ids: list[str] = Field(min_length=1, max_length=100)
    plan_type: str = Field(pattern="^(free|vip|svip)$")
    duration_days: int = Field(default=30, ge=1, le=3650)


class BillingCreateOrderPayload(BaseModel):
    """创建会员订单的请求体。"""
    plan_type: str = Field(pattern="^(vip|svip)$")


# ============================================================
# 密码重置相关模型
# ============================================================
class ForgotPasswordPayload(BaseModel):
    """
    请求发送密码重置验证码。
    
    email: 用户注册邮箱
    """
    email: str


class VerifyCodePayload(BaseModel):
    """
    验证密码重置验证码。
    
    email: 用户邮箱
    code: 6 位数字验证码
    """
    email: str
    code: str = Field(min_length=6, max_length=6)


class ResetPasswordPayload(BaseModel):
    """
    重置密码请求体。
    
    email: 用户邮箱
    code: 6 位数字验证码
    new_password: 新密码（6-64 位）
    """
    email: str
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=6, max_length=64)


# ============================================================
# 高级配置模型 - 记忆条目
# ============================================================
class MemoryEntryPayload(BaseModel):
    """
    记忆条目（World Info）请求体。
    
    keywords: 逗号分隔的关键词列表
    trigger_logic: 触发逻辑 - any(任意匹配) / all(全部匹配)
    content: 触发时注入的内容
    position: 插入位置 - before(前) / after(后)
    priority: 优先级，数字越小越优先
    comment: 备注
    is_active: 是否启用
    category_id: 可选，对应本角色的 memory_categories.id；不传或 null 表示不分类
    """
    keywords: str = Field(min_length=1, max_length=500)
    trigger_logic: str = Field(default="any", pattern="^(any|all)$")
    content: str = Field(min_length=1, max_length=4000)
    position: str = Field(default="before", pattern="^(before|after)$")
    priority: int = Field(default=100, ge=0, le=9999)
    comment: str = Field(default="", max_length=200)
    is_active: int = Field(default=1, ge=0, le=1)
    category_id: str | None = Field(default=None)


# ============================================================
# 高级配置模型 - 开场白
# ============================================================
class GreetingPayload(BaseModel):
    """
    多阶段开场白请求体。
    
    content: 开场白内容
    story_phase: 关系阶段 - stranger/acquaintance/friend/lover
    mood: 心情 - neutral/happy/sad/angry/flirty
    priority: 优先级
    storyline_id: 关联的剧情线ID（可选）
    is_active: 是否启用
    """
    content: str = Field(min_length=1, max_length=2000)
    story_phase: str = Field(
        default="stranger",
        pattern="^(stranger|acquaintance|friend|lover)$"
    )
    mood: str = Field(
        default="neutral",
        pattern="^(neutral|happy|sad|angry|flirty)$"
    )
    priority: int = Field(default=100, ge=0, le=9999)
    storyline_id: str | None = Field(default=None)
    is_active: int = Field(default=1, ge=0, le=1)


# ============================================================
# 高级配置模型 - 剧情线
# ============================================================
class StorylinePayload(BaseModel):
    """
    剧情线请求体。
    
    name: 剧情线名称
    description: 描述
    unlock_score: 解锁所需好感度
    sort_order: 排序
    is_default: 是否为默认剧情线
    is_active: 是否启用
    """
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    unlock_score: int = Field(default=0, ge=0)
    sort_order: int = Field(default=0)
    is_default: int = Field(default=0, ge=0, le=1)
    is_active: int = Field(default=1, ge=0, le=1)


# ============================================================
# 高级配置模型 - 关键词测试
# ============================================================
class KeywordTestPayload(BaseModel):
    """
    关键词测试请求体。
    
    text: 要测试的文本
    """
    text: str = Field(min_length=1, max_length=2000)


# ============================================================
# 高级配置模型 - 后置规则
# ============================================================
class PostRulePayload(BaseModel):
    """
    后置规则请求体。
    
    后置规则在 AI 回复后应用，用于控制输出格式、过滤内容等。
    
    name: 规则名称
    content: 规则内容，放在历史记录后
    storyline_id: 仅对特定剧情线生效（可选）
    story_phase: 仅对特定阶段生效（可选）- stranger/acquaintance/friend/lover
    priority: 优先级，数字越小越优先
    is_active: 是否启用
    """
    name: str = Field(min_length=1, max_length=50)
    content: str = Field(min_length=1, max_length=5000)
    storyline_id: str | None = Field(default=None)
    story_phase: str | None = Field(default=None)
    priority: int = Field(default=100, ge=0, le=9999)
    is_active: int = Field(default=1, ge=0, le=1)


# ============================================================
# 高级配置模型 - 剧情事件
# ============================================================
class StoryEventPayload(BaseModel):
    """
    剧情事件请求体。
    
    当用户好感度达到指定值时自动触发的事件。
    
    title: 事件标题
    description: 事件描述
    trigger_score: 触发所需好感度
    unlocked_memory_ids: 解锁的记忆ID列表，逗号分隔
    unlocked_greeting_ids: 解锁的开场白ID列表，逗号分隔
    unlocked_storyline_id: 解锁的剧情线ID
    event_content: 事件触发时的特殊对话内容
    sort_order: 排序
    is_active: 是否启用
    """
    title: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=2000)
    trigger_score: int = Field(default=0, ge=0)
    unlocked_memory_ids: str = Field(default="", max_length=500)
    unlocked_greeting_ids: str = Field(default="", max_length=500)
    unlocked_storyline_id: str | None = Field(default=None)
    event_content: str = Field(default="", max_length=5000)
    sort_order: int = Field(default=0)
    is_active: int = Field(default=1, ge=0, le=1)


# ============================================================
# 高级配置模型 - 记忆分类
# ============================================================
class MemoryCategoryPayload(BaseModel):
    """
    记忆分类请求体。
    
    name: 分类名称
    description: 分类描述
    color: UI颜色，如 #FF6B6B
    sort_order: 排序权重
    """
    name: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=500)
    color: str = Field(default="#1890FF", max_length=7)
    sort_order: int = Field(default=0)


# ============================================================
# Regenerate / Continue 功能模型
# ============================================================
class RegeneratePayload(BaseModel):
    """
    重新生成 AI 回复的请求体。

    message_id: 要重新生成的 AI 消息 ID（chat_messages.id，UUID 格式）
    """
    message_id: str = Field(min_length=1)


class ContinuePayload(BaseModel):
    """
    继续（追加）生成 AI 回复的请求体。

    message_id: 要继续生成的 AI 消息 ID（chat_messages.id，UUID 格式）
    """
    message_id: str = Field(min_length=1)
