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

from pydantic import BaseModel, Field, field_validator, model_validator

from constants.mood import Mood
from constants.story_phase import StoryPhase


# 从枚举动态生成验证正则，确保与常量定义始终同步
_MOOD_PATTERN = "^(" + "|".join(m.value for m in Mood) + ")$"
_STORY_PHASE_PATTERN = "^(" + "|".join(sp.value for sp in StoryPhase) + ")$"


def _normalize_email(value: str) -> str:
    value = value.strip().lower()
    if '@' not in value or '.' not in value.split('@')[-1]:
        raise ValueError('无效的邮箱格式')
    return value


def _normalize_optional_email(value: str | None) -> str | None:
    if value is None:
        return None
    return _normalize_email(value)


def _validate_password_length(value: str) -> str:
    if len(value) < 8:
        raise ValueError('密码至少需要8位')
    if len(value) > 64:
        raise ValueError('密码不能超过64位')
    return value


def _strip_text(value: str) -> str:
    return value.strip()


def _normalize_optional_trimmed(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _validate_required_trimmed(value: str, error_message: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(error_message)
    return value


# ============================================================
# 认证相关模型
# ============================================================
class _EmailPayload(BaseModel):
    email: str = Field(max_length=255)

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        return _normalize_email(v)


class _OptionalEmailPayload(BaseModel):
    email: str | None = Field(default=None, max_length=255)

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        return _normalize_optional_email(v)


class LoginPayload(_EmailPayload):
    """登录接口请求体。密码长度不限制，兼容旧版短密码。"""
    password: str = Field(min_length=1, max_length=64)


class RegisterPayload(_EmailPayload):
    """
    注册接口的请求体。

    nickname 是可选的，不填时用邮箱前缀代替（比如 hello@example.com → hello）。
    """
    password: str = Field(min_length=8, max_length=64)
    nickname: str = Field(default="", max_length=20)

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        return _validate_password_length(v)

    @field_validator('nickname')
    @classmethod
    def validate_nickname(cls, v: str) -> str:
        return _strip_text(v)


# ============================================================
# 角色相关模型
# ============================================================
class _CharacterIdPayload(BaseModel):
    character_id: str

    @field_validator('character_id')
    @classmethod
    def validate_character_id(cls, v: str) -> str:
        return _validate_required_trimmed(v, '角色ID不能为空')


class CharacterProfileUpdatePayload(_CharacterIdPayload):
    """更新用户对某个角色的个性化配置。"""
    remark: str = Field(default="", max_length=40)
    custom_signature: str = Field(default="", max_length=100)


class CharacterActionPayload(_CharacterIdPayload):
    """角色相关操作的通用请求体（只传角色 ID）。"""


class ClearChatPayload(_CharacterIdPayload):
    """
    清空聊天并重新选择剧情线入口。

    greeting_index：
      - None / -1 → 使用角色默认开场白（first_mes）
      - 0          → 同上（0 号即 first_mes）
      - 1, 2, …   → alternate_greetings 列表下标（从 1 起算，与前端展示序号一致）
      - 也支持字符串格式的 DB 主键 ID（兼容 greetings 接口返回值）
    """
    greeting_index: int | str = Field(default=-1)


# ============================================================
# 聊天相关模型
# ============================================================
class ChatSendPayload(_CharacterIdPayload):
    """发送聊天消息的请求体。"""
    message: str = Field(min_length=1, max_length=2000)

    @field_validator('message')
    @classmethod
    def validate_message(cls, v: str) -> str:
        v = _validate_required_trimmed(v, '消息不能为空')
        if len(v) > 2000:
            raise ValueError('消息不能超过2000字符')
        return v


class GuestMessageItem(BaseModel):
    """
    游客前端临时历史消息条目（不存库，仅用于单次上下文）。

    role: 'user' | 'assistant'
    content: 消息内容
    """
    role: str
    content: str = Field(min_length=1, max_length=2000)

    @field_validator('role')
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ('user', 'assistant'):
            raise ValueError('role 必须是 user 或 assistant')
        return v

    @field_validator('content')
    @classmethod
    def validate_content(cls, v: str) -> str:
        return _strip_text(v)


class GuestChatPayload(_CharacterIdPayload):
    """
    游客试聊接口请求体。不需要 token，不存消息，只做一次 AI 调用。

    guest_history: 最多传 10 条前端临时历史，让 AI 保留上下文
    """
    message: str = Field(min_length=1, max_length=500)
    guest_history: list[GuestMessageItem] = Field(default_factory=list, max_length=10)


class MergeGuestHistoryPayload(_CharacterIdPayload):
    """游客登录后将聊天历史合并到用户账号。"""
    messages: list[GuestMessageItem] = Field(default_factory=list, max_length=50)


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


class AdminUserEditPayload(_OptionalEmailPayload):
    """管理后台编辑用户信息。"""
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
class ForgotPasswordPayload(_EmailPayload):
    """
    请求发送密码重置验证码。

    email: 用户注册邮箱
    """


class VerifyCodePayload(_EmailPayload):
    """
    验证密码重置验证码。

    email: 用户邮箱
    code: 6 位数字验证码
    """
    code: str = Field(min_length=6, max_length=6)


class ResetPasswordPayload(_EmailPayload):
    """
    重置密码请求体。

    email: 用户邮箱
    code: 6 位数字验证码
    new_password: 新密码（8-64 位）
    """
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8, max_length=64)


# ============================================================
# 高级配置共享模型
# ============================================================
class _PriorityActivePayload(BaseModel):
    priority: int = Field(default=100, ge=0, le=9999)
    is_active: int = Field(default=1, ge=0, le=1)


class _SortOrderPayload(BaseModel):
    sort_order: int = Field(default=0)


class _SortOrderActivePayload(_SortOrderPayload):
    is_active: int = Field(default=1, ge=0, le=1)


class _OptionalCategoryIdPayload(BaseModel):
    category_id: str | None = Field(default=None)

    @field_validator('category_id')
    @classmethod
    def validate_category_id(cls, v: str | None) -> str | None:
        return _normalize_optional_trimmed(v)


class _OptionalStorylineIdPayload(BaseModel):
    storyline_id: str | None = Field(default=None)

    @field_validator('storyline_id')
    @classmethod
    def validate_storyline_id(cls, v: str | None) -> str | None:
        return _normalize_optional_trimmed(v)


class _OptionalUnlockedStorylineIdPayload(BaseModel):
    unlocked_storyline_id: str | None = Field(default=None)

    @field_validator('unlocked_storyline_id')
    @classmethod
    def validate_unlocked_storyline_id(cls, v: str | None) -> str | None:
        return _normalize_optional_trimmed(v)


# ============================================================
# 高级配置模型 - 记忆条目
# ============================================================
class MemoryEntryPayload(_OptionalCategoryIdPayload, _PriorityActivePayload):
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
    selective: 选择性注入，1=仅关键词匹配时注入（默认），0=始终注入
    constant: 常驻注入，1=不需要关键词匹配每轮都注入，0=需要匹配（默认）
    sticky: 一旦触发后持续注入的轮数，0=不持续（默认）
    cooldown: 触发后冷却轮数，0=无冷却（默认）
    """
    keywords: str = Field(min_length=1, max_length=500)
    trigger_logic: str = Field(default="any", pattern="^(any|all)$")
    content: str = Field(min_length=1, max_length=4000)
    position: str = Field(default="before", pattern="^(before|after)$")
    comment: str = Field(default="", max_length=200)
    selective: int = Field(default=1, ge=0, le=1)
    constant: int = Field(default=0, ge=0, le=1)
    sticky: int = Field(default=0, ge=0, le=999)
    cooldown: int = Field(default=0, ge=0, le=999)


# ============================================================
# 高级配置模型 - 开场白
# ============================================================
class GreetingPayload(_OptionalStorylineIdPayload, _PriorityActivePayload):
    """
    多阶段开场白请求体。

    content: 开场白内容
    story_phase: 关系阶段 - stranger/acquaintance/friend/lover
    mood: 心情 - neutral/happy/sad/angry/flirty
    priority: 优先级
    storyline_id: 关联的剧情线ID（可选）
    is_active: 是否启用
    comment: 管理员备注
    """
    content: str = Field(min_length=1, max_length=2000)
    story_phase: str = Field(
        default="stranger",
        pattern=_STORY_PHASE_PATTERN
    )
    mood: str = Field(
        default="neutral",
        pattern=_MOOD_PATTERN
    )
    comment: str = Field(default="", max_length=200)


# ============================================================
# 高级配置模型 - 剧情线
# ============================================================
class StorylinePayload(_SortOrderActivePayload):
    """
    剧情线请求体。

    storyline_id: 剧情线短标识（如 awakening_path），用于内部引用
    title: 剧情线显示名称
    name: 兼容字段，未传时自动取 title 的值
    description: 描述
    unlock_score: 解锁所需好感度
    stages: 剧情阶段名称列表（如 ["觉醒","探索","深入","终章"]）
    sort_order: 排序
    is_default: 是否为默认剧情线
    is_active: 是否启用
    """
    storyline_id: str = Field(default="", max_length=100)
    title: str = Field(default="", max_length=100)
    name: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=500)
    unlock_score: int = Field(default=0, ge=0)
    unlock_condition: str | None = Field(default=None, max_length=500)
    stages: list[str] = Field(default_factory=list)
    is_default: int = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def _fill_defaults(self) -> "StorylinePayload":
        """title 和 name 互为 fallback，storyline_id 未设则自动生成。"""
        if not self.title and self.name:
            self.title = self.name
        if not self.name and self.title:
            self.name = self.title
        if not self.title and not self.name:
            raise ValueError("title 和 name 至少填一个")
        if not self.storyline_id:
            # 用 title 的拼音或简单标识，这里自动取 name 的下划线版本
            import re
            self.storyline_id = re.sub(r"[^a-zA-Z0-9_]", "", self.name.replace(" ", "_").lower()) or "auto"
        return self


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
class PostRulePayload(_OptionalStorylineIdPayload, _PriorityActivePayload):
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
    story_phase: str | None = Field(default=None)


# ============================================================
# 高级配置模型 - 剧情事件
# ============================================================
class StoryEventPayload(_OptionalUnlockedStorylineIdPayload, _SortOrderActivePayload):
    """
    剧情事件请求体。

    当用户好感度达到指定值时自动触发的事件。

    title: 事件标题
    description: 事件描述
    trigger_score: 触发所需好感度
    trigger_custom_key: 逗号分隔的custom_vars键名，需全部存在且非空才触发（轻量复合条件）
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
    trigger_custom_key: str = Field(default="", max_length=500)
    unlocked_memory_ids: str = Field(default="", max_length=500)
    unlocked_greeting_ids: str = Field(default="", max_length=500)
    event_content: str = Field(default="", max_length=5000)


# ============================================================
# 高级配置模型 - 记忆分类
# ============================================================
class MemoryCategoryPayload(_SortOrderPayload):
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


# ============================================================
# Regenerate / Continue 功能模型
# ============================================================
class _MessageIdPayload(BaseModel):
    message_id: str = Field(min_length=1)


class RegeneratePayload(_MessageIdPayload):
    """
    重新生成 AI 回复的请求体。

    message_id: 要重新生成的 AI 消息 ID（chat_messages.id，UUID 格式）
    """


class ContinuePayload(_MessageIdPayload):
    """
    继续（追加）生成 AI 回复的请求体。

    message_id: 要继续生成的 AI 消息 ID（chat_messages.id，UUID 格式）
    """
