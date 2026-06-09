/**
 * char-editor-fields.js - 角色编辑页字段配置与纯函数。
 *
 * 只维护展示层信息架构，不改变后端字段名和保存 payload。
 */

const AdminCharEditorFields = (() => {
  const BEGINNER_FIXED_FIELDS = [
    'name',
    'subtitle',
    'opening_message',
    'avatar_url',
    'cover_url',
    'is_visible',
    'home_priority',
    'system_prompt',
    'card_type',
  ];

  const BEGINNER_RL_FIELDS = ['base_profile', 'examples'];

  const FIELD_META = {
    name: { label: '角色名', desc: '玩家在广场和聊天页看到的名字。', type: 'text' },
    abbr: { label: '简称 abbr', desc: '聊天头像文字兜底和后台搜索使用；不填时建议与角色名一致。', type: 'text' },
    subtitle: { label: '简介（副标题）', desc: '广场卡片和聊天签名展示，建议 30-60 字。', type: 'textarea', rows: 3 },
    tags: { label: '标签', desc: '前台展示标签，可用逗号分隔，或 JSON 数组如 ["治愈","现代"]。', type: 'textarea', rows: 2 },
    avatar_url: { label: '头像图片 avatar_url', desc: '聊天头像；支持本地绝对路径、/frontend/... 静态路径或 http(s) URL。推荐 1:1 正方形。', type: 'text' },
    cover_url: { label: '封面图片 cover_url', desc: '广场卡片/详情封面；留空时前台会用头像兜底。推荐 4:3。', type: 'text' },
    opening_message: { label: '默认开场白', desc: '用户首次进入、或清空聊天选择默认开场时看到的第一句话。', type: 'textarea', rows: 8 },
    system_prompt: { label: '展示字段兜底主指令', desc: '当运行时优先主指令为空时才作为 prompt 兜底；日常可写角色一句话定性。', type: 'textarea', rows: 4 },
    description: { label: '对外描述', desc: '角色详情页展示；当角色底稿为空时也会作为 AI 角色底稿兜底。', type: 'textarea', rows: 4 },
    is_visible: { label: '广场可见', desc: '控制角色是否出现在前台角色广场。', type: 'select', options: [['1', '可见（前台展示）'], ['0', '隐藏（不展示）']] },
    home_priority: { label: '广场排序 home_priority', desc: '前台广场主排序，数字越小越靠前。', type: 'number' },
    sort_order: { label: '后台列表排序 sort_order', desc: '后台列表和部分兜底排序使用，数字越小越靠前。', type: 'number' },
    card_type: { label: '玩法类型', desc: '决定聊天模式和下方字段显示：对话陪伴 intimate / 剧情沙盒 scenario。', type: 'select', options: [['intimate', '对话陪伴'], ['scenario', '剧情沙盒']] },
    required_plan: { label: '访问档位', desc: '控制谁能看到/进入这个角色。guest=游客可见，svip=仅 SVIP 可用。', type: 'select', options: [['guest', '游客可访问'], ['free', '注册用户可访问'], ['vip', '仅 VIP 可访问'], ['svip', '仅 SVIP 可访问']] },
    import_locked: { label: '导入锁定', desc: '导入兼容字段；1=展示字段已锁定，不应被重导入覆盖。', type: 'select', options: [['1', '已锁定'], ['0', '未锁定']] },
    affection_enabled: { label: '前台显示状态栏', desc: '只控制玩家是否看见进度条/阶段/心情；不关闭后台规则计算。', type: 'select', options: [['1', '显示'], ['0', '隐藏']] },
    affection_rules_json: { label: '规则配置 JSON（高级调试）', desc: '由上方可视化编辑器同步生成；日常不要手写，除非排查规则。', type: 'textarea', rows: 8 },
    phase_behaviors_json: { label: '阶段行为定制', desc: '为每个关系/剧情阶段定义独特行为倾向；留空使用系统默认。', type: 'phase_behaviors' },
    life_profile_json: { label: '人生档案', desc: '仅对话陪伴使用，会作为独立 layer 注入给 AI。', type: 'life_profile', cardTypes: 'intimate' },
  };

  const READONLY_META = {
    asset_type: { label: '资源类型 asset_type', desc: '导入/运行时资产类型，只读。', rows: 2 },
    embedded_format: { label: '嵌入格式 embedded_format', desc: '导入格式，只读。', rows: 2 },
    mock_reply_style: { label: 'mock_reply_style', desc: '历史兼容占位风格，只读。', rows: 3 },
    import_diagnostics: { label: '导入诊断 import_diagnostics', desc: '导入问题诊断信息，只读。', rows: 10 },
  };

  const RL_FIELD_META = {
    primary_system_prompt: { label: '运行时优先主指令', desc: 'runtime_cache_json.primary_system_prompt，真实 prompt 优先使用它；和上方兜底主指令冲突时以这里为准。', rows: 4, cardTypes: 'both' },
    base_profile: { label: '角色底稿 base_profile', desc: 'AI 实际看到的人物背景、身份、外貌、关系等核心设定。', rows: 20, cardTypes: 'both' },
    archetype: { label: '角色原型', desc: '对话陪伴专属，影响阶段行为兜底模板；自定义阶段行为优先级更高。', type: 'select', options: [['', '不设置'], ['温柔', '温柔 - 治愈包容'], ['高冷', '高冷/傲娇 - 反差魅力'], ['天然呆', '天然呆 - 真诚跳脱'], ['成熟', '成熟 - 沉稳可靠'], ['病娇', '病娇 - 强占有与不安']], cardTypes: 'intimate' },
    personality: { label: '性格与表达风格', desc: '角色说话方式、口癖、情绪模式和禁忌话题。', rows: 6, cardTypes: 'both' },
    scenario: { label: '剧情场景 scenario', desc: '剧情沙盒专属：故事发生的时间、地点、背景和当前局势。', rows: 8, cardTypes: 'scenario' },
    world_rules: { label: '世界规则 world_rules', desc: '世界观、行为边界、剧情禁忌和不可违背规则。', rows: 10, cardTypes: 'both' },
    examples: { label: '示例对话 examples', desc: '展示角色理想说话风格；建议 3-5 组，避免过长。', rows: 10, cardTypes: 'both' },
    post_history_rules: { label: '回复规则提醒 post_history_rules', desc: '每轮对话末尾注入；适合短规则，长规则建议放世界书/后置规则。', rows: 6, cardTypes: 'both' },
    alternate_greetings: { label: '导入兼容多开场白', desc: '导入卡备选开场白；正式运营优先使用「剧情」页的开场白管理。用 --- 分隔。', rows: 12, cardTypes: 'scenario' },
    opening_message: { label: '导入兼容开场白', desc: 'runtime 里的开场兼容字段；当前默认开场主入口是上方「默认开场白」和「剧情」页开场白。', rows: 6, cardTypes: 'both' },
    structured_outline: { label: '结构化大纲 structured_outline', desc: '导入解析结果，JSON 格式；主要用于排障，不直接作为日常编辑入口。', rows: 16, cardTypes: 'both', jsonType: 'object' },
    world_info_before: { label: '导入世界书-前置', desc: '导入卡常驻 before_char 内容；日常运营优先迁到「世界书」页。', rows: 8, cardTypes: 'both' },
    world_info_after: { label: '导入世界书-后置', desc: '导入卡常驻 after_char 内容；日常运营优先迁到「世界书」页。', rows: 8, cardTypes: 'both' },
    conditional_entries: { label: '导入关键词触发词条', desc: 'JSON 数组；命中关键词后动态注入。建议改用「世界书」页维护。', rows: 8, cardTypes: 'both', jsonType: 'array' },
    extension_hints: { label: '扩展提示 extension_hints', desc: 'JSON 对象；目前主要支持 depth_prompt 等高级导入能力。', rows: 4, cardTypes: 'both', jsonType: 'object' },
  };

  const READONLY_SECTION_FIELDS = ['asset_type', 'embedded_format', 'mock_reply_style', 'import_diagnostics'];
  const DANGEROUS_RL_JSON_FIELDS = {
    conditional_entries: 'array',
    extension_hints: 'object',
    structured_outline: 'object',
  };
  const AFFECTION_META_KEYS = new Set(['enabled', 'daily_cap', 'allow_regression', 'show_bar', 'scenario_type']);

  const SECTION_DEFS = [
    {
      id: 'listing',
      title: '上架信息',
      desc: '玩家能不能看到、看到什么、排在什么位置，都在这里配置。',
      fixedFields: ['name', 'abbr', 'subtitle', 'opening_message', 'tags', 'avatar_url', 'cover_url', 'is_visible', 'home_priority', 'sort_order', 'required_plan'],
    },
    {
      id: 'aiCore',
      title: 'AI 核心设定',
      desc: '这些内容会进入或兜底进入 prompt，直接影响角色像不像、会不会跑偏。',
      fixedFields: ['system_prompt', 'description'],
      rlFields: ['base_profile', 'personality', 'scenario', 'world_rules', 'examples'],
    },
    {
      id: 'playConfig',
      title: '玩法配置',
      desc: '配置玩法类型、人生档案、阶段行为和好感度/沉浸度规则。',
      fixedFields: ['card_type', 'life_profile_json', 'affection_enabled', 'affection_rules_json', 'phase_behaviors_json'],
      rlFields: ['archetype'],
    },
    {
      id: 'advanced',
      title: '高级兼容/排障',
      desc: '导入卡兼容和 prompt 排障字段。日常运营尽量少改，改前建议看 Prompt 预览。',
      collapsed: true,
      fixedFields: ['import_locked'],
      rlFields: [
        'primary_system_prompt',
        'opening_message',
        'post_history_rules',
        'alternate_greetings',
        'world_info_before',
        'world_info_after',
        'conditional_entries',
        'extension_hints',
        'structured_outline',
      ],
      readonlyFields: READONLY_SECTION_FIELDS,
    },
  ];

  function shouldShowForCardType(meta, cardType) {
    const types = meta?.cardTypes || 'both';
    return types === 'both' || types === cardType;
  }

  function uniqueInOrder(items) {
    const out = [];
    const seen = new Set();
    for (const item of items) {
      if (!item || seen.has(item)) continue;
      seen.add(item);
      out.push(item);
    }
    return out;
  }

  function filterFixedFields(fields, cardType, isBeginnerMode) {
    return fields.filter((field) => {
      const meta = FIELD_META[field];
      if (!meta) return false;
      if (!shouldShowForCardType(meta, cardType)) return false;
      if (isBeginnerMode && !BEGINNER_FIXED_FIELDS.includes(field)) return false;
      return true;
    });
  }

  function filterRlFields(fields, cardType, isBeginnerMode, availableRlKeys) {
    const available = new Set(availableRlKeys || []);
    return fields.filter((field) => {
      const meta = RL_FIELD_META[field];
      if (!meta) return !isBeginnerMode && available.has(field);
      if (!shouldShowForCardType(meta, cardType)) return false;
      if (isBeginnerMode && !BEGINNER_RL_FIELDS.includes(field)) return false;
      if (!available.has(field) && !['base_profile', 'examples', 'personality', 'scenario', 'world_rules', 'archetype'].includes(field)) return false;
      return true;
    });
  }

  function collectUnknownRlFields(availableRlKeys) {
    const known = new Set(listAllKnownRlFields());
    return (availableRlKeys || []).filter((field) => field && !known.has(field));
  }

  function resolveEditorLayout({ cardType = 'intimate', isBeginnerMode = true, availableRlKeys = [] } = {}) {
    const layout = [];
    for (const def of SECTION_DEFS) {
      if (isBeginnerMode && def.id === 'advanced') continue;
      const sourceRlFields = !isBeginnerMode && def.id === 'advanced'
        ? uniqueInOrder([...(def.rlFields || []), ...collectUnknownRlFields(availableRlKeys)])
        : (def.rlFields || []);
      const fixedFields = filterFixedFields(def.fixedFields || [], cardType, isBeginnerMode);
      const rlFields = filterRlFields(sourceRlFields, cardType, isBeginnerMode, availableRlKeys);
      const readonlyFields = isBeginnerMode ? [] : (def.readonlyFields || []);
      if (!fixedFields.length && !rlFields.length && !readonlyFields.length) continue;
      layout.push({ ...def, fixedFields, rlFields, readonlyFields });
    }
    return { sections: layout };
  }

  function listAllFixedFields() {
    return uniqueInOrder(SECTION_DEFS.flatMap((section) => section.fixedFields || []));
  }

  function listAllKnownRlFields() {
    return uniqueInOrder(SECTION_DEFS.flatMap((section) => section.rlFields || []));
  }

  function parseObject(raw, fallback = {}) {
    try {
      const parsed = typeof raw === 'string' ? JSON.parse(raw || '{}') : raw;
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : fallback;
    } catch (_) {
      return fallback;
    }
  }

  function upsertAffectionMeta(rawRules, key, value) {
    const rules = parseObject(rawRules, {});
    if (value === '' || value == null) {
      delete rules[key];
    } else {
      rules[key] = value;
    }
    return rules;
  }

  function validateDangerousRuntimeJson(rlKey, rawValue) {
    const expected = DANGEROUS_RL_JSON_FIELDS[rlKey];
    if (!expected) return { ok: true };
    const text = String(rawValue || '').trim();
    if (!text) return { ok: true };
    try {
      const parsed = JSON.parse(text);
      if (expected === 'array' && !Array.isArray(parsed)) {
        return { ok: false, message: `${RL_FIELD_META[rlKey].label} 必须是 JSON 数组` };
      }
      if (expected === 'object' && (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))) {
        return { ok: false, message: `${RL_FIELD_META[rlKey].label} 必须是 JSON 对象` };
      }
      return { ok: true, value: parsed, hasValue: true };
    } catch (_) {
      return { ok: false, message: `${RL_FIELD_META[rlKey].label} 须为合法 JSON` };
    }
  }

  function validateAffectionRulesJson(rawValue) {
    const text = String(rawValue || '').trim();
    if (!text) return { ok: true, value: {} };
    try {
      const parsed = JSON.parse(text);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return { ok: false, message: '规则配置 JSON 必须是 JSON 对象' };
      }
      for (const [key, value] of Object.entries(parsed)) {
        if (AFFECTION_META_KEYS.has(key)) continue;
        if (value != null && typeof value === 'object') {
          return { ok: false, message: `规则配置 JSON 的 ${key} 不能是数组或对象` };
        }
      }
      return { ok: true, value: parsed };
    } catch (_) {
      return { ok: false, message: '规则配置 JSON 不是合法 JSON' };
    }
  }

  function hasAnyJsonValue(raw) {
    const obj = parseObject(raw, {});
    return Object.values(obj).some((value) => {
      if (value == null) return false;
      if (typeof value === 'string') return value.trim() !== '';
      if (Array.isArray(value)) return value.length > 0;
      if (typeof value === 'object') return Object.keys(value).length > 0;
      return Boolean(value);
    });
  }

  function getRiskWarnings({
    cardType,
    lifeProfileJson,
    systemPrompt,
    primarySystemPrompt,
    openingMessage,
    affectionEnabled,
    affectionRulesJson,
  }) {
    const warnings = [];
    if (cardType === 'scenario' && hasAnyJsonValue(lifeProfileJson)) {
      warnings.push('剧情沙盒不使用人生档案，这段内容保存后不会进入 scenario prompt。');
    }
    const systemText = String(systemPrompt || '').trim();
    const primaryText = String(primarySystemPrompt || '').trim();
    if (systemText && primaryText && systemText !== primaryText) {
      warnings.push('展示字段主指令和运行时优先主指令差异较大，请确认没有互相冲突。');
    }
    if (!String(openingMessage || '').trim()) {
      warnings.push('默认开场白为空，用户首次进入时体验会很突兀。');
    }
    const rules = parseObject(affectionRulesJson, {});
    const barHidden = String(affectionEnabled) === '0';
    const rulesEnabled = rules.enabled !== false;
    if (barHidden && rulesEnabled) {
      warnings.push('前台状态栏已隐藏，但规则计算仍启用；用户看不到进度变化。');
    }
    return warnings;
  }

  return {
    FIELD_META,
    READONLY_META,
    RL_FIELD_META,
    READONLY_SECTION_FIELDS,
    DANGEROUS_RL_JSON_FIELDS,
    AFFECTION_META_KEYS,
    BEGINNER_FIXED_FIELDS,
    BEGINNER_RL_FIELDS,
    resolveEditorLayout,
    listAllFixedFields,
    listAllKnownRlFields,
    upsertAffectionMeta,
    validateDangerousRuntimeJson,
    validateAffectionRulesJson,
    getRiskWarnings,
  };
})();

if (typeof globalThis !== 'undefined') {
  globalThis.AdminCharEditorFields = AdminCharEditorFields;
}
