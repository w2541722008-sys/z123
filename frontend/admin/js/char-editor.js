/**
 * char-editor.js - 编辑角色标签页逻辑
 *
 * 包含：编辑面板渲染、字段元信息、runtime_layers 编辑、
 * 人生档案/阶段行为编辑器、字段构建工具函数。
 * 依赖：utils.js, api.js, state.js, config.js, char-editor-affection.js
 */

// ============================================================
// 工具函数
// ============================================================
function safeParseJSON(str, fallback = {}) {
  try {
    return JSON.parse(str);
  } catch {
    return fallback;
  }
}

// ============================================================
// 固定字段元信息（表字段）
// ============================================================
const FIXED_FIELD_META = {
  name:               { label: '角色名', desc: '显示在广场和聊天页的名字', type: 'text' },
  abbr:               { label: '简称 abbr', desc: '聊天内称呼等', type: 'text' },
  subtitle:           { label: '简介（副标题）', desc: '广场卡片下方显示，60字以内吸引用户', type: 'textarea', rows: 3 },
  tags:               { label: '标签', desc: '逗号分隔，或 JSON 数组如 ["标签A","标签B"]', type: 'textarea', rows: 2 },
  avatar_url:         { label: '头像图片 avatar_url', desc: '聊天头像；支持本地绝对路径、/frontend/... 静态路径或 http(s) URL。推荐 1:1 正方形。', type: 'text' },
  cover_url:          { label: '封面图片 cover_url', desc: '广场卡片/详情封面；支持本地绝对路径、/frontend/... 静态路径或 http(s) URL。推荐 4:3，主体放上半部分。', type: 'text' },
  opening_message:    { label: '开场白', desc: '第一次进入聊天时AI说的第一句话', type: 'textarea', rows: 8 },
  system_prompt:      { label: '主指令（System Prompt）', desc: '固定前置指令，如"始终扮演XXX"', type: 'textarea', rows: 4 },
  description:        { label: '描述', desc: '角色简短描述', type: 'textarea', rows: 4 },
  is_visible:         { label: '是否在广场显示', desc: '1=可见，0=隐藏', type: 'select', options: [['1','✅ 可见（前台展示）'],['0','🙈 隐藏（不展示）']] },
  home_priority:      { label: '广场排序 home_priority', desc: '数字越小越靠前（0最前）', type: 'number' },
  sort_order:         { label: '列表排序 sort_order', desc: '管理列表与部分排序用，数值越小越靠前', type: 'number' },
  card_type:          { label: '卡类型', desc: '决定聊天模式', type: 'select', options: [['intimate','💞 对话陪伴'],['scenario','🎭 剧情沙盒']] },
  required_plan:      { label: '访问档位', desc: '控制谁能看到/进入这个角色。guest=游客可见，svip=仅SVIP可用', type: 'select', options: [['guest','游客可访问'],['free','注册用户可访问'],['vip','仅 VIP 可访问'],['svip','仅 SVIP 可访问']] },
  import_locked:      { label: '导入锁定', desc: '1=展示字段已锁定不被重导入覆盖', type: 'select', options: [['1','🔒 已锁定'],['0','🔓 未锁定']] },
  affection_enabled:  { label: '好感度系统', desc: '是否启用好感度追踪', type: 'select', options: [['1','❤️ 启用'],['0','🚫 禁用']] },
  affection_rules_json: { label: '好感度规则 JSON', desc: 'JSON 对象字符串，写入 affection_rules_json 列', type: 'textarea', rows: 8 },
  phase_behaviors_json: { label: '🎭 阶段行为定制', desc: 'JSON 对象，为每个关系阶段定制行为倾向。如 {"stranger":"对新顾客热情推荐","friend":"主动分享烦恼"}', type: 'phase_behaviors' },
  life_profile_json: { label: '👤 人生档案', desc: '角色的完整人生背景（童年、家庭、工作等），AI每轮都能看到', type: 'life_profile' },
};

const READONLY_META = {
  asset_type:         { label: '资源类型 asset_type', desc: 'character / world / hybrid 等（只读）', rows: 2 },
  embedded_format:  { label: '嵌入格式 embedded_format', desc: 'json / ccv3 / chara 等（只读）', rows: 2 },
  mock_reply_style: { label: 'mock_reply_style', desc: '占位风格文本（只读）', rows: 3 },
  import_diagnostics: { label: '导入诊断 import_diagnostics', desc: 'JSON 数组字符串（只读）', rows: 10 },
};

// runtime_layers 字段中文说明（cardTypes: 'both' | 'intimate' | 'scenario'）
const RL_FIELD_META = {
  primary_system_prompt: { label: '主System Prompt（深层）', desc: '从角色卡解析出的核心指令', rows: 4, cardTypes: 'both' },
  base_profile:          { label: '📖 角色档案（base_profile）', desc: '角色的人物背景、身份、外貌、性格等主要设定——最核心的内容在这里', rows: 20, cardTypes: 'both' },
  personality:           { label: '性格描述', desc: '角色性格特征', rows: 6, cardTypes: 'both' },
  scenario:              { label: '🎬 场景设定', desc: '剧情沙盒专属：故事发生的时间/地点/背景', rows: 8, cardTypes: 'scenario' },
  world_rules:           { label: '🌐 世界规则', desc: '世界观设定、规则、禁忌', rows: 10, cardTypes: 'both' },
  examples:              { label: '💬 示例对话', desc: '展示角色说话风格的例句', rows: 10, cardTypes: 'both' },
  post_history_rules:    { label: '📌 对话规则（每轮提醒）', desc: '每次对话末尾注入的格式/行为规则', rows: 6, cardTypes: 'both' },
  alternate_greetings:   { label: '🎭 多开场白列表', desc: '剧情沙盒专属：各条剧情线的开场白（用 ---分隔）', rows: 12, cardTypes: 'scenario' },
  opening_message:       { label: '开场白（深层）', desc: 'runtime里的开场白，与表字段同步', rows: 6, cardTypes: 'both' },
  structured_outline:    { label: '📋 结构化大纲', desc: '角色卡的结构化解析结果（JSON格式）', rows: 16, cardTypes: 'both' },
  world_info_before:     { label: '🌍 世界书-前置词条', desc: 'character_book 里 before_char 的词条内容', rows: 8, cardTypes: 'both' },
  world_info_after:      { label: '🌍 世界书-后置词条', desc: 'character_book 里 after_char 的词条内容', rows: 8, cardTypes: 'both' },
  conditional_entries:   { label: '⚡ 条件触发词条', desc: '关键词触发的world info词条（JSON格式）', rows: 8, cardTypes: 'both' },
  extension_hints:       { label: '扩展提示', desc: '其他扩展信息', rows: 4, cardTypes: 'both' },
};

// 字段分区（固定字段）— cardTypes: 'both' | 'intimate' | 'scenario'
const FIXED_SECTIONS = [
  { title: '📋 基础展示信息', fields: ['name', 'abbr', 'subtitle', 'tags', 'opening_message'], cardTypes: 'both' },
  { title: '🖼️ 角色形象', fields: ['avatar_url', 'cover_url'], cardTypes: 'both' },
  { title: '⚙️ 系统与广场', fields: ['system_prompt', 'description', 'is_visible', 'home_priority', 'sort_order', 'card_type', 'required_plan', 'import_locked', 'affection_enabled'], cardTypes: 'both' },
  { title: '👤 人生档案', fields: ['life_profile_json'], cardTypes: 'intimate' },
  { title: '❤️ 好感度', fields: ['affection_rules_json'], cardTypes: 'both' },
  { title: '🎭 阶段行为', fields: ['phase_behaviors_json'], cardTypes: 'both' },
];

const READONLY_SECTION_FIELDS = ['asset_type', 'embedded_format', 'mock_reply_style', 'import_diagnostics'];

// runtime_layers 显示顺序
const RL_DISPLAY_ORDER = [
  'base_profile', 'personality', 'scenario', 'world_rules', 'examples',
  'post_history_rules', 'alternate_greetings',
  'world_info_before', 'world_info_after', 'conditional_entries',
  'primary_system_prompt', 'opening_message', 'structured_outline', 'extension_hints',
];

// ============================================================
// 编辑面板引导卡
// ============================================================
function buildEditGuideHtml(character) {
  const typeAdviceMap = {
    intimate: '对话陪伴型最看重：角色底稿、开场白、记忆条目和说话风格稳定。',
    scenario: '剧情沙盒型最看重：剧情线、开场白差异和事件推进是否连贯。',
  };
  const typeAdvice = typeAdviceMap[character?.card_type || 'intimate'] || typeAdviceMap.intimate;

  // 检查是否显示引导卡
  const hideGuide = localStorage.getItem('admin_hide_guide') === 'true';
  if (hideGuide) return '';

  return `
    <div class="guide-card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;">
        <div class="guide-title">🧭 新手配置顺序</div>
        <button class="btn btn-ghost btn-sm" data-action="hide-guide" style="padding:2px 8px;font-size:11px;">不再显示</button>
      </div>
      <div class="guide-desc">如果你现在对项目还不熟，可以直接按这个顺序做，不需要一次把所有字段都填满。</div>
      <ol class="guide-list">
        <li>先补齐：角色名、简介、主指令、开场白。</li>
        <li>再看「角色核心内容」里的 base_profile / examples，这两块最影响角色像不像真人。</li>
        <li>去「世界书」里补 3 条以上高频记忆，去「剧情」里做 2 档以上开场白。</li>
        <li>最后打开 Prompt 预览，确认 AI 实际吃到的内容没有重复、冲突和空洞。</li>
      </ol>
      <div class="guide-chip-row">
        <span class="guide-chip">先做核心，不要一次全填</span>
        <span class="guide-chip">Prompt 预览是排查页</span>
        <span class="guide-chip">剧情线 / 事件可以后补</span>
      </div>
      <div class="guide-note">当前角色建议：${escHtml(typeAdvice)}</div>
    </div>
  `;
}

// ============================================================
// 字段 HTML 生成器
// ============================================================
function makeFieldHtml(fieldId, label, desc, type, val, extraOpts) {
  // 字段长度提示（带建议范围）
  let lenTip = '';
  if (typeof val === 'string' && val.length > 0) {
    const ranges = {
      subtitle: '建议 30-60',
      opening_message: '建议 100-500',
      system_prompt: '建议 200-500',
      description: '建议 100-300',
      'rl__base_profile': '建议 2000-8000',
      'rl__personality': '建议 500-3000',
      'rl__scenario': '建议 200-2000',
      'rl__examples': '建议 500-3000',
    };
    const range = ranges[fieldId] || '';
    lenTip = `<span class="field-len">${val.length} 字${range ? ` (${range})` : ''}</span>`;
  }
  let inputHtml = '';

  if (type === 'textarea') {
    const rows = extraOpts?.rows || 4;
    inputHtml = `<textarea id="field-${fieldId}" rows="${rows}" oninput="updateLen(this)">${escHtml(String(val ?? ''))}</textarea>`;
  } else if (type === 'select') {
    const normalizedVal = typeof val === 'boolean' ? (val ? '1' : '0') : String(val ?? '');
    inputHtml = `<select id="field-${fieldId}">`;
    for (const [optVal, optLabel] of (extraOpts?.options || [])) {
      inputHtml += `<option value="${optVal}" ${normalizedVal === String(optVal) ? 'selected' : ''}>${optLabel}</option>`;
    }
    inputHtml += '</select>';
  } else if (type === 'number') {
    inputHtml = `<input type="number" id="field-${fieldId}" value="${val ?? 0}" />`;
  } else if (type === 'readonly_textarea') {
    const rows = extraOpts?.rows || 4;
    inputHtml = `<textarea readonly rows="${rows}" style="opacity:.92;cursor:default;width:100%;background:#0f0f13;border:1px solid #2a2a3a;border-radius:8px;color:#9ca3af;padding:10px 12px;font-size:13px;line-height:1.5;resize:vertical;">${escHtml(String(val ?? ''))}</textarea>`;
  } else   if (type === 'life_profile') {
    return renderLifeProfileEditor(val);
  } else if (type === 'phase_behaviors') {
    return renderPhaseBehaviorsEditor(val);
  } else {
    inputHtml = `<input type="text" id="field-${fieldId}" value="${escHtml(String(val ?? ''))}" />`;
  }

  return `<div class="field-group">
    <label>${label} ${lenTip}</label>
    <div class="field-desc">${desc}</div>
    ${inputHtml}
  </div>`;
}

function updateLen(el) {
  const lenEl = el.closest('.field-group')?.querySelector('.field-len');
  if (lenEl) lenEl.textContent = el.value.length + ' 字';
}

// ============================================================
// 阶段行为定制编辑器
// ============================================================
function renderPhaseBehaviorsEditor(jsonStr) {
  const parsed = safeParseJSON(jsonStr || '{}');
  const ct = (AdminState.currentCharData && AdminState.currentCharData.card_type) || 'intimate';
  const labels = PHASE_LABEL_MAPS?.[ct] || { stranger: '陌生人', acquaintance: '熟人', friend: '朋友', lover: '恋人' };
  const placeholders = {
    stranger: '例如：对新顾客热情推荐试吃，聊甜品话题，但不主动聊私事',
    acquaintance: '例如：开始记住对方口味偏好，偶尔分享工作趣事',
    friend: '例如：把对方当特别的人，主动分享烦恼和梦想，偶尔撒娇',
    lover: '例如：直接表达想念和爱意，用亲昵称呼，偶尔吃醋',
  };
  const rows = Object.entries(labels).map(([key, label]) => `
    <div class="life-profile-field">
      <label>${escHtml(label)}（${escHtml(key)}）</label>
      <textarea id="phase-behavior-${escHtml(key)}" rows="3" placeholder="${escHtml(placeholders[key] || '描述该阶段的行为倾向')}" oninput="syncPhaseBehaviorsEditor()">${escHtml(parsed[key] || '')}</textarea>
    </div>
  `).join('');
  return `
    <div class="field-group">
      <div class="field-label">🎭 阶段行为定制 <span class="field-hint">为每个关系阶段定义独特的行为倾向，替代系统默认文案</span></div>
      <div class="life-profile-editor">
        ${rows}
        <div class="life-profile-note">
          💡 提示：<br />
          - 留空表示使用系统默认行为倾向<br />
          - 每个阶段建议控制在 100 字以内，过长的行为规则会分散 AI 注意力<br />
          - 重点描述该阶段角色的核心互动模式，而非面面俱到
        </div>
      </div>
      <textarea id="field-phase_behaviors_json" style="display:none;">${escHtml(jsonStr || '{}')}</textarea>
    </div>
  `;
}

function syncPhaseBehaviorsEditor() {
  const target = document.getElementById('field-phase_behaviors_json');
  if (!target) return;
  const obj = {};
  ['stranger', 'acquaintance', 'friend', 'lover'].forEach(phase => {
    const val = document.getElementById(`phase-behavior-${phase}`)?.value?.trim() || '';
    if (val) obj[phase] = val;
  });
  target.value = JSON.stringify(obj, null, 2);
}

// ============================================================
// 人生档案编辑器
// ============================================================
function renderLifeProfileEditor(jsonStr) {
  const parsed = safeParseJSON(jsonStr || '{}');
  return `
    <div class="field-group">
      <div class="field-label">👤 人生档案 <span class="field-hint">AI每轮都能看到，让角色像真人一样有完整背景</span></div>
      <div class="life-profile-editor">
        <div class="life-profile-field">
          <label>基本信息（姓名、年龄、职业）</label>
          <textarea id="life-profile-basic" rows="3" placeholder="例如：林深，28岁，互联网公司产品经理" oninput="syncLifeProfileEditor()">${escHtml(parsed.basic_info || '')}</textarea>
        </div>
        <div class="life-profile-field">
          <label>童年经历</label>
          <textarea id="life-profile-childhood" rows="4" placeholder="例如：出生在江南小镇，父母经营茶馆。小学时因为内向被同学孤立..." oninput="syncLifeProfileEditor()">${escHtml(parsed.childhood || '')}</textarea>
        </div>
        <div class="life-profile-field">
          <label>家庭背景</label>
          <textarea id="life-profile-family" rows="3" placeholder="例如：父亲林国华，60岁，退休茶艺师。母亲陈婉清，58岁..." oninput="syncLifeProfileEditor()">${escHtml(parsed.family || '')}</textarea>
        </div>
        <div class="life-profile-field">
          <label>工作经历</label>
          <textarea id="life-profile-work" rows="4" placeholder="例如：2018年毕业于浙江大学计算机系，2018-2020字节跳动..." oninput="syncLifeProfileEditor()">${escHtml(parsed.work || '')}</textarea>
        </div>
        <div class="life-profile-field">
          <label>性格特点</label>
          <textarea id="life-profile-personality" rows="3" placeholder="例如：表面温和，内心有主见。喜欢倾听，不喜欢争论..." oninput="syncLifeProfileEditor()">${escHtml(parsed.personality || '')}</textarea>
        </div>
        <div class="life-profile-field">
          <label>生活习惯</label>
          <textarea id="life-profile-habits" rows="3" placeholder="例如：早上7点起床，喜欢晨跑。周末喜欢去咖啡馆看书..." oninput="syncLifeProfileEditor()">${escHtml(parsed.habits || '')}</textarea>
        </div>
        <div class="life-profile-field">
          <label>重要经历</label>
          <textarea id="life-profile-events" rows="4" placeholder="例如：大学时暗恋过学姐但没表白。工作第二年因项目失败陷入低谷..." oninput="syncLifeProfileEditor()">${escHtml(parsed.important_events || '')}</textarea>
        </div>
        <div class="life-profile-note">
          💡 提示：<br />
          - 填写的内容会在每轮对话中注入给AI，让角色回答更真实一致<br />
          - 不需要全部填满，根据角色需要选择性填写<br />
          - 当用户问到相关话题时，AI会自然地分享这些背景信息
        </div>
      </div>
      <textarea id="field-life_profile_json" style="display:none;">${escHtml(jsonStr || '{}')}</textarea>
    </div>
  `;
}

function syncLifeProfileEditor() {
  const target = document.getElementById('field-life_profile_json');
  if (!target) return;
  const obj = {
    basic_info: document.getElementById('life-profile-basic')?.value?.trim() || '',
    childhood: document.getElementById('life-profile-childhood')?.value?.trim() || '',
    family: document.getElementById('life-profile-family')?.value?.trim() || '',
    work: document.getElementById('life-profile-work')?.value?.trim() || '',
    personality: document.getElementById('life-profile-personality')?.value?.trim() || '',
    habits: document.getElementById('life-profile-habits')?.value?.trim() || '',
    important_events: document.getElementById('life-profile-events')?.value?.trim() || '',
  };
  target.value = JSON.stringify(obj, null, 2);
}

// ============================================================
// 渲染编辑面板
// ============================================================
function renderEditPanel(c) {
  const panel = document.getElementById('tab-edit');
  AdminState.currentRlFields = [];

  // 从 localStorage 读取模式
  const isBeginnerMode = localStorage.getItem('admin_beginner_mode') !== 'false';

  let html = `<div class="edit-panel">
    <h2>${escHtml(c.name || '')}</h2>
    <div class="char-id">ID: ${c.id} &nbsp;|&nbsp; 类型: ${c.card_type || '?'} &nbsp;|&nbsp; 来源: ${escHtml(c.source_path || '未知')}</div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
      <div style="font-size:12px;color:var(--text-dim);">
        ${isBeginnerMode ? '🎯 新手模式：只显示核心字段' : '🔧 完整模式：显示所有字段'}
      </div>
      <button class="btn btn-ghost btn-sm" data-action="toggle-beginner-mode">
        ${isBeginnerMode ? '切换到完整模式' : '切换到新手模式'}
      </button>
    </div>
    ${buildEditGuideHtml(c)}`;

  // 固定字段分区（根据 card_type 和模式过滤）
  const cardType = c.card_type || 'intimate';
  const beginnerCoreFields = ['name', 'subtitle', 'opening_message', 'system_prompt', 'avatar_url', 'cover_url', 'card_type', 'is_visible', 'home_priority'];

  for (const section of FIXED_SECTIONS) {
    if (section.cardTypes !== 'both' && section.cardTypes !== cardType) continue;

    // 新手模式：只显示包含核心字段的分区
    if (isBeginnerMode) {
      const hasCore = section.fields.some(f => beginnerCoreFields.includes(f));
      if (!hasCore) continue;
    }

    html += `<div class="section-title">${section.title}</div>`;
    for (const field of section.fields) {
      const meta = FIXED_FIELD_META[field];
      if (!meta) continue;

      // 新手模式：跳过非核心字段
      if (isBeginnerMode && !beginnerCoreFields.includes(field)) continue;

      if (field === 'affection_rules_json') {
        html += renderAffectionRuleEditor(c[field] ?? '{}');
      }
      html += makeFieldHtml(field, meta.label, meta.desc, meta.type, c[field] ?? '', meta);
    }
  }

  // 新手模式：隐藏只读字段
  if (!isBeginnerMode) {
    html += `<div class="section-title">📎 导入与资源（只读）</div>`;
    for (const field of READONLY_SECTION_FIELDS) {
      const meta = READONLY_META[field];
      if (!meta) continue;
      html += makeFieldHtml(field, meta.label, meta.desc, 'readonly_textarea', c[field] ?? '', meta);
    }
  }

  // runtime_layers 字段（根据 card_type 和模式过滤）
  const rlFields = [];
  // 核心字段根据类型区分
  const CORE_RL_FIELDS = cardType === 'scenario'
    ? ['base_profile', 'examples', 'scenario', 'alternate_greetings', 'world_rules']
    : ['base_profile', 'examples', 'personality', 'world_rules'];

  // 新手模式：只显示核心字段
  const rlFieldsToShow = isBeginnerMode ? ['base_profile', 'examples'] : RL_DISPLAY_ORDER;

  // 按预定顺序先加有数据的
  for (const rlKey of rlFieldsToShow) {
    const fullKey = `rl__${rlKey}`;
    if (fullKey in c) rlFields.push(rlKey);
  }

  if (!isBeginnerMode) {
    // 有但不在预定顺序里的，补到末尾
    for (const k of Object.keys(c)) {
      if (k.startsWith('rl__') && !rlFields.includes(k.slice(4))) {
        rlFields.push(k.slice(4));
      }
    }
    // 确保核心字段始终显示（即使为空）
    for (const coreKey of CORE_RL_FIELDS) {
      if (!rlFields.includes(coreKey)) {
        rlFields.push(coreKey);
      }
    }
  } else {
    // 新手模式：确保 base_profile 和 examples 显示
    for (const coreKey of ['base_profile', 'examples']) {
      if (!rlFields.includes(coreKey)) {
        rlFields.push(coreKey);
      }
    }
  }

  if (rlFields.length > 0) {
    html += `<div class="section-title">🎭 角色核心内容（AI实际看到的设定）
      <span style="font-size:11px;color:#666;font-weight:400">— 这里才是角色的真正内容</span>
    </div>`;

    for (const rlKey of rlFields) {
      const fullKey = `rl__${rlKey}`;
      const val = c[fullKey] ?? '';
      const meta = RL_FIELD_META[rlKey];
      // 根据 cardTypes 过滤字段
      if (meta?.cardTypes && meta.cardTypes !== 'both' && meta.cardTypes !== cardType) continue;
      const label = meta?.label || rlKey;
      const desc = meta?.desc || `runtime_layers.${rlKey}`;
      const rows = meta?.rows || 6;
      if (!val && !meta) continue;
      AdminState.currentRlFields.push(rlKey);
      html += makeFieldHtml(fullKey, label, desc, 'textarea', val, { rows });
    }
  }

  html += `<div class="save-bar">
    <button class="btn btn-success" data-action="save-char">💾 保存修改</button>
    <button class="btn btn-danger" data-action="delete-current-character">🗑️ 删除角色</button>
    <span id="save-status" class="save-status"></span>
  </div>
  </div>`;

  panel.innerHTML = html;

  document.querySelectorAll('[data-affection-key]').forEach(input => {
    input.addEventListener('input', syncAffectionRulesEditor);
  });
  validateAffectionRulesEditor();
}
