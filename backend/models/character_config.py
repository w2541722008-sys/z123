"""
角色配置系统数据模型
===================

为自运营 AI 男友项目设计的完整角色配置系统，覆盖高质量角色卡的所有核心玩法机制。

核心表结构：
- character_memories: 关键词触发的记忆条目（World Info 机制）
- memory_categories: 记忆分类标签（剧情线分类）
- character_greetings: 多阶段开场白
- character_storylines: 剧情线/世界观配置
- character_post_rules: 后置规则（输出控制）
- story_events: 剧情事件（好感度解锁）

设计原则：
- 清爽有效，每张表都有明确用途
- 支持多剧情线切换（职业线/幼年序等）
- 可视化配置友好

作者: AI Assistant
日期: 2026-03-29
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ============================================================================
# Enums - 枚举类型定义
# ============================================================================

class StoryPhase(str, Enum):
    """关系阶段枚举"""
    STRANGER = "stranger"      # 陌生人
    ACQUAINTANCE = "acquaintance"  # 熟人
    FRIEND = "friend"          # 朋友
    LOVER = "lover"            # 恋人


class Mood(str, Enum):
    """心情状态枚举"""
    HAPPY = "happy"            # 开心
    NEUTRAL = "neutral"        # 一般
    COLD = "cold"              # 冷淡
    ANGRY = "angry"            # 生气


class MemoryPosition(str, Enum):
    """记忆插入位置"""
    BEFORE = "before"          # 放在历史记录前
    AFTER = "after"            # 放在历史记录后


class TriggerLogic(str, Enum):
    """触发逻辑类型"""
    ANY = "any"                # 任意关键词匹配
    ALL = "all"                # 所有关键词都匹配
    NOT = "not"                # 不包含关键词时触发


# ============================================================================
# Memory System - 记忆系统模型
# ============================================================================

class MemoryCategoryBase(BaseModel):
    """记忆分类基础模型"""
    name: str = Field(..., min_length=1, max_length=50, description="分类名称，如'职业线'")
    description: Optional[str] = Field(None, max_length=500, description="分类描述")
    color: Optional[str] = Field(None, max_length=7, description="UI颜色，如#FF6B6B")
    sort_order: int = Field(0, description="排序权重")


class MemoryCategoryCreate(MemoryCategoryBase):
    """创建记忆分类请求模型"""
    pass


class MemoryCategoryUpdate(BaseModel):
    """更新记忆分类请求模型"""
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    color: Optional[str] = Field(None, max_length=7)
    sort_order: Optional[int] = None


class MemoryCategory(MemoryCategoryBase):
    """记忆分类完整模型"""
    id: int
    character_id: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class CharacterMemoryBase(BaseModel):
    """角色记忆条目基础模型"""
    # 关键词配置
    keywords: str = Field(
        ..., 
        min_length=1, 
        max_length=500,
        description="触发关键词，逗号分隔，如'妈妈,家人,父母'"
    )
    trigger_logic: TriggerLogic = Field(
        TriggerLogic.ANY,
        description="触发逻辑：any=任意匹配，all=全部匹配，not=反向触发"
    )
    
    # 内容配置
    content: str = Field(
        ..., 
        min_length=1, 
        max_length=10000,
        description="记忆内容，注入到prompt中"
    )
    
    # 分类与位置
    category_id: Optional[int] = Field(None, description="所属分类ID")
    position: MemoryPosition = Field(
        MemoryPosition.BEFORE,
        description="插入位置：before=历史前，after=历史后"
    )
    
    # 控制参数
    priority: int = Field(100, ge=0, le=1000, description="优先级，数字小的先插入")
    is_active: bool = Field(True, description="是否启用")
    
    # 触发限制
    max_recursion: int = Field(1, ge=0, le=10, description="单次对话最大触发次数")
    
    # 备注
    comment: Optional[str] = Field(None, max_length=200, description="备注说明")


class CharacterMemoryCreate(CharacterMemoryBase):
    """创建记忆条目请求模型"""
    pass


class CharacterMemoryUpdate(BaseModel):
    """更新记忆条目请求模型"""
    keywords: Optional[str] = Field(None, min_length=1, max_length=500)
    trigger_logic: Optional[TriggerLogic] = None
    content: Optional[str] = Field(None, min_length=1, max_length=10000)
    category_id: Optional[int] = None
    position: Optional[MemoryPosition] = None
    priority: Optional[int] = Field(None, ge=0, le=1000)
    is_active: Optional[bool] = None
    max_recursion: Optional[int] = Field(None, ge=0, le=10)
    comment: Optional[str] = Field(None, max_length=200)


class CharacterMemory(CharacterMemoryBase):
    """角色记忆条目完整模型"""
    id: int
    character_id: str
    created_at: datetime
    updated_at: datetime
    
    # 关联数据
    category: Optional[MemoryCategory] = None
    
    class Config:
        from_attributes = True


class MemoryTriggerResult(BaseModel):
    """记忆触发结果"""
    memory_id: int
    keywords_matched: List[str]
    content: str
    position: MemoryPosition
    priority: int


# ============================================================================
# Greeting System - 开场白系统模型
# ============================================================================

class CharacterGreetingBase(BaseModel):
    """角色开场白基础模型"""
    # 触发条件
    story_phase: StoryPhase = Field(..., description="适用关系阶段")
    mood: Mood = Field(Mood.NEUTRAL, description="适用心情状态")
    
    # 内容
    content: str = Field(
        ..., 
        min_length=1, 
        max_length=5000,
        description="开场白内容"
    )
    
    # 关联剧情线
    storyline_id: Optional[int] = Field(None, description="所属剧情线ID")
    
    # 控制参数
    priority: int = Field(100, ge=0, le=1000, description="优先级，数字小的优先")
    is_active: bool = Field(True, description="是否启用")
    
    # 使用统计
    use_count: int = Field(0, description="使用次数")
    
    # 备注
    comment: Optional[str] = Field(None, max_length=200, description="备注，如'职业线开场'")


class CharacterGreetingCreate(CharacterGreetingBase):
    """创建开场白请求模型"""
    pass


class CharacterGreetingUpdate(BaseModel):
    """更新开场白请求模型"""
    story_phase: Optional[StoryPhase] = None
    mood: Optional[Mood] = None
    content: Optional[str] = Field(None, min_length=1, max_length=5000)
    storyline_id: Optional[int] = None
    priority: Optional[int] = Field(None, ge=0, le=1000)
    is_active: Optional[bool] = None
    comment: Optional[str] = Field(None, max_length=200)


class CharacterGreeting(CharacterGreetingBase):
    """角色开场白完整模型"""
    id: int
    character_id: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class GreetingSelector(BaseModel):
    """开场白选择器"""
    story_phase: StoryPhase
    mood: Mood = Mood.NEUTRAL
    storyline_id: Optional[int] = None
    exclude_ids: List[int] = Field(default_factory=list, description="排除已用过的ID")


# ============================================================================
# Storyline System - 剧情线系统模型
# ============================================================================

class CharacterStorylineBase(BaseModel):
    """角色剧情线基础模型"""
    name: str = Field(
        ..., 
        min_length=1, 
        max_length=50,
        description="剧情线名称，如'职业线'、'幼年序'"
    )
    description: Optional[str] = Field(None, max_length=1000, description="剧情线描述")
    
    # 解锁条件
    unlock_score: int = Field(0, ge=0, description="解锁所需好感度")
    is_default: bool = Field(False, description="是否为默认剧情线")
    
    # 状态
    is_active: bool = Field(True, description="是否启用")
    sort_order: int = Field(0, description="排序权重")


class CharacterStorylineCreate(CharacterStorylineBase):
    """创建剧情线请求模型"""
    pass


class CharacterStorylineUpdate(BaseModel):
    """更新剧情线请求模型"""
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=1000)
    unlock_score: Optional[int] = Field(None, ge=0)
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class CharacterStoryline(CharacterStorylineBase):
    """角色剧情线完整模型"""
    id: int
    character_id: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# ============================================================================
# Post Rules - 后置规则模型
# ============================================================================

class CharacterPostRuleBase(BaseModel):
    """角色后置规则基础模型"""
    name: str = Field(..., min_length=1, max_length=50, description="规则名称")
    content: str = Field(
        ..., 
        min_length=1, 
        max_length=5000,
        description="规则内容，放在历史记录后"
    )
    
    # 触发条件
    storyline_id: Optional[int] = Field(None, description="仅对特定剧情线生效")
    story_phase: Optional[StoryPhase] = Field(None, description="仅对特定阶段生效")
    
    # 控制参数
    priority: int = Field(100, ge=0, le=1000, description="优先级")
    is_active: bool = Field(True, description="是否启用")


class CharacterPostRuleCreate(CharacterPostRuleBase):
    """创建后置规则请求模型"""
    pass


class CharacterPostRuleUpdate(BaseModel):
    """更新后置规则请求模型"""
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    content: Optional[str] = Field(None, min_length=1, max_length=5000)
    storyline_id: Optional[int] = None
    story_phase: Optional[StoryPhase] = None
    priority: Optional[int] = Field(None, ge=0, le=1000)
    is_active: Optional[bool] = None


class CharacterPostRule(CharacterPostRuleBase):
    """角色后置规则完整模型"""
    id: int
    character_id: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# ============================================================================
# Story Events - 剧情事件模型
# ============================================================================

class StoryEventBase(BaseModel):
    """剧情事件基础模型"""
    title: str = Field(..., min_length=1, max_length=100, description="事件标题")
    description: Optional[str] = Field(None, max_length=2000, description="事件描述")
    
    # 触发条件
    trigger_score: int = Field(
        ..., 
        ge=0, 
        description="触发所需好感度"
    )
    
    # 解锁内容
    unlocked_memory_ids: Optional[str] = Field(
        None, 
        max_length=500,
        description="解锁的记忆ID列表，逗号分隔"
    )
    unlocked_greeting_ids: Optional[str] = Field(
        None,
        max_length=500,
        description="解锁的开场白ID列表，逗号分隔"
    )
    unlocked_storyline_id: Optional[int] = Field(
        None,
        description="解锁的剧情线ID"
    )
    
    # 事件内容
    event_content: Optional[str] = Field(
        None,
        max_length=5000,
        description="事件触发时的特殊对话内容"
    )
    
    # 状态
    is_active: bool = Field(True, description="是否启用")
    sort_order: int = Field(0, description="排序权重")


class StoryEventCreate(StoryEventBase):
    """创建剧情事件请求模型"""
    pass


class StoryEventUpdate(BaseModel):
    """更新剧情事件请求模型"""
    title: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    trigger_score: Optional[int] = Field(None, ge=0)
    unlocked_memory_ids: Optional[str] = Field(None, max_length=500)
    unlocked_greeting_ids: Optional[str] = Field(None, max_length=500)
    unlocked_storyline_id: Optional[int] = None
    event_content: Optional[str] = Field(None, max_length=5000)
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class StoryEvent(StoryEventBase):
    """剧情事件完整模型"""
    id: int
    character_id: str
    created_at: datetime
    updated_at: datetime
    
    # 是否已触发（由业务层填充）
    is_triggered: bool = Field(False, description="当前用户是否已触发")
    
    class Config:
        from_attributes = True


# ============================================================================
# Character Config Summary - 角色配置汇总
# ============================================================================

class CharacterConfigSummary(BaseModel):
    """角色配置汇总信息"""
    character_id: int
    character_name: str
    
    # 统计信息
    memory_count: int
    memory_category_count: int
    greeting_count: int
    storyline_count: int
    post_rule_count: int
    story_event_count: int
    
    # 默认配置
    default_storyline_id: Optional[int] = None
    
    # 最近更新
    last_updated: datetime


class CharacterConfigExport(BaseModel):
    """角色配置导出模型（用于备份/迁移）"""
    character_name: str
    export_time: datetime
    
    categories: List[MemoryCategory]
    memories: List[CharacterMemory]
    greetings: List[CharacterGreeting]
    storylines: List[CharacterStoryline]
    post_rules: List[CharacterPostRule]
    story_events: List[StoryEvent]


class CharacterConfigImport(BaseModel):
    """角色配置导入模型"""
    config_data: CharacterConfigExport
    target_character_id: Optional[int] = Field(
        None,
        description="导入到指定角色，为空则创建新角色"
    )
    overwrite_existing: bool = Field(
        False,
        description="是否覆盖现有配置"
    )
