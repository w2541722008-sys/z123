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

const FIXED_FIELD_META = AdminCharEditorFields.FIELD_META;
const READONLY_META = AdminCharEditorFields.READONLY_META;
const RL_FIELD_META = AdminCharEditorFields.RL_FIELD_META;

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
    const rawJsonAttrs = fieldId === 'affection_rules_json' ? ' data-affection-raw-json="true"' : '';
    inputHtml = `<textarea id="field-${fieldId}" rows="${rows}" data-update-len="true"${rawJsonAttrs}>${escHtml(String(val ?? ''))}</textarea>`;
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
    inputHtml = `<textarea readonly class="field-readonly" rows="${rows}">${escHtml(String(val ?? ''))}</textarea>`;
  } else if (type === 'life_profile') {
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

function makeScenarioTypeField(rulesJson) {
  const rules = safeParseJSON(rulesJson || '{}');
  const scenarioType = rules.scenario_type || 'adventure';
  return `<div class="field-group">
    <label>剧情类型（scenario_type）</label>
    <div class="field-desc">决定剧情沙盒使用哪套 System Prompt 和沉浸度事件；保存时仍写回 affection_rules_json.scenario_type。</div>
    <select id="field-scenario_type" data-affection-refresh="true">
      <option value="adventure" ${scenarioType === 'adventure' ? 'selected' : ''}>冒险剧情</option>
      <option value="romance" ${scenarioType === 'romance' ? 'selected' : ''}>恋爱剧情</option>
    </select>
  </div>`;
}

function makeRawAffectionJsonField(value) {
  const meta = FIXED_FIELD_META.affection_rules_json;
  return `<details class="raw-json-details">
    <summary>高级调试：查看/手写规则 JSON</summary>
    <div class="raw-json-note">日常请使用上方可视化编辑器。这里会随编辑器同步，手写错误会导致保存失败。</div>
    ${makeFieldHtml('affection_rules_json', meta.label, meta.desc, meta.type, value, meta)}
  </details>`;
}

function buildSectionTitle(section) {
  const collapsedClass = section.collapsed ? ' collapsed' : '';
  return `<div class="section-title${collapsedClass}" data-action="toggle-section-collapse">
    <span>${escHtml(section.title)}</span>
  </div>`;
}

function buildSectionContentStart(section) {
  const collapsedClass = section.collapsed ? ' collapsed' : '';
  return `<div class="section-content${collapsedClass}">
    ${section.desc ? `<div class="section-help">${escHtml(section.desc)}</div>` : ''}`;
}

function collectAvailableRlKeys(c) {
  return Object.keys(c || {})
    .filter(k => k.startsWith('rl__'))
    .map(k => k.slice(4));
}

function renderRiskWarnings(c) {
  const warnings = AdminCharEditorFields.getRiskWarnings({
    cardType: c.card_type || 'intimate',
    lifeProfileJson: c.life_profile_json || '{}',
    systemPrompt: c.system_prompt || '',
    primarySystemPrompt: c.rl__primary_system_prompt || '',
    openingMessage: c.opening_message || '',
    affectionEnabled: c.affection_enabled,
    affectionRulesJson: c.affection_rules_json || '{}',
  });
  if (!warnings.length) return '';
  return `<div class="editor-risk-card">
    <div class="editor-risk-title">保存前请留意</div>
    ${warnings.map(item => `<div class="editor-risk-item">${escHtml(item)}</div>`).join('')}
  </div>`;
}

function renderFixedField(field, c) {
  const meta = FIXED_FIELD_META[field];
  if (!meta) return '';
  if (field === 'affection_rules_json') {
    return `${renderAffectionRuleEditor(c[field] ?? '{}')}${makeRawAffectionJsonField(c[field] ?? '{}')}`;
  }
  return makeFieldHtml(field, meta.label, meta.desc, meta.type, c[field] ?? '', meta);
}

function renderRlField(rlKey, c) {
  const fullKey = `rl__${rlKey}`;
  const val = c[fullKey] ?? '';
  const meta = RL_FIELD_META[rlKey] || {
    label: `兼容字段 ${rlKey}`,
    desc: `runtime_layers.${rlKey}，导入卡保留的未知字段；不确定用途时建议先看 Prompt 预览。`,
    rows: 6,
  };
  AdminState.currentRlFields.push(rlKey);
  const rlType = meta.type || 'textarea';
  const rlExtra = rlType === 'select' ? { options: meta.options } : { rows: meta.rows || 6 };
  return makeFieldHtml(fullKey, meta.label, meta.desc, rlType, val, rlExtra);
}

function collectVisibleEditorValues(baseData) {
  const next = { ...(baseData || {}) };
  for (const field of AdminCharEditorFields.listAllFixedFields()) {
    const el = document.getElementById(`field-${field}`);
    if (!el) continue;
    next[field] = el.value;
  }
  for (const rlKey of AdminState.currentRlFields || []) {
    const el = document.getElementById(`field-rl__${rlKey}`);
    if (!el) continue;
    next[`rl__${rlKey}`] = el.value;
  }
  return next;
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
      <textarea id="phase-behavior-${escHtml(key)}" rows="3" placeholder="${escHtml(placeholders[key] || '描述该阶段的行为倾向')}" data-phase-behavior-input="true">${escHtml(parsed[key] || '')}</textarea>
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
          <textarea id="life-profile-basic" rows="3" placeholder="例如：林深，28岁，互联网公司产品经理" data-life-profile-input="true">${escHtml(parsed.basic_info || '')}</textarea>
        </div>
        <div class="life-profile-field">
          <label>童年经历</label>
          <textarea id="life-profile-childhood" rows="4" placeholder="例如：出生在江南小镇，父母经营茶馆。小学时因为内向被同学孤立..." data-life-profile-input="true">${escHtml(parsed.childhood || '')}</textarea>
        </div>
        <div class="life-profile-field">
          <label>家庭背景</label>
          <textarea id="life-profile-family" rows="3" placeholder="例如：父亲林国华，60岁，退休茶艺师。母亲陈婉清，58岁..." data-life-profile-input="true">${escHtml(parsed.family || '')}</textarea>
        </div>
        <div class="life-profile-field">
          <label>工作经历</label>
          <textarea id="life-profile-work" rows="4" placeholder="例如：2018年毕业于浙江大学计算机系，2018-2020字节跳动..." data-life-profile-input="true">${escHtml(parsed.work || '')}</textarea>
        </div>
        <div class="life-profile-field">
          <label>性格特点</label>
          <textarea id="life-profile-personality" rows="3" placeholder="例如：表面温和，内心有主见。喜欢倾听，不喜欢争论..." data-life-profile-input="true">${escHtml(parsed.personality || '')}</textarea>
        </div>
        <div class="life-profile-field">
          <label>生活习惯</label>
          <textarea id="life-profile-habits" rows="3" placeholder="例如：早上7点起床，喜欢晨跑。周末喜欢去咖啡馆看书..." data-life-profile-input="true">${escHtml(parsed.habits || '')}</textarea>
        </div>
        <div class="life-profile-field">
          <label>重要经历</label>
          <textarea id="life-profile-events" rows="4" placeholder="例如：大学时暗恋过学姐但没表白。工作第二年因项目失败陷入低谷..." data-life-profile-input="true">${escHtml(parsed.important_events || '')}</textarea>
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
        ${isBeginnerMode ? '新手模式：只显示核心字段' : '完整模式：显示所有字段'}
      </div>
      <button class="mode-toggle ${isBeginnerMode ? 'beginner' : 'advanced'}" data-action="toggle-beginner-mode">
        <span class="toggle-dot"></span> ${isBeginnerMode ? '🎯 新手模式' : '🔧 完整模式'}
      </button>
    </div>
    ${buildEditGuideHtml(c)}`;

  const cardType = c.card_type || 'intimate';
  html += renderRiskWarnings(c);

  const availableRlKeys = collectAvailableRlKeys(c);
  const layout = AdminCharEditorFields.resolveEditorLayout({
    cardType,
    isBeginnerMode,
    availableRlKeys,
  });

  for (const section of layout.sections) {
    html += buildSectionTitle(section);
    html += buildSectionContentStart(section);

    for (const field of section.fixedFields || []) {
      html += renderFixedField(field, c);
      if (field === 'card_type' && cardType === 'scenario') {
        html += makeScenarioTypeField(c.affection_rules_json || '{}');
      }
    }

    for (const rlKey of section.rlFields || []) {
      html += renderRlField(rlKey, c);
    }

    for (const field of section.readonlyFields || []) {
      const meta = READONLY_META[field];
      if (!meta) continue;
      html += makeFieldHtml(field, meta.label, meta.desc, 'readonly_textarea', c[field] ?? '', meta);
    }

    html += `</div>`;
  }

  html += `<div class="save-bar">
    <button class="btn btn-success" data-action="save-char">💾 保存修改</button>
    <button class="btn btn-danger" data-action="delete-current-character">🗑️ 删除角色</button>
    <span id="save-status" class="save-status"></span>
    <span id="dirty-indicator" class="dirty-indicator d-none">● 有未保存修改</span>
  </div>
  </div>`;

  panel.innerHTML = html;

  validateAffectionRulesEditor();

  // 监听编辑面板所有输入变更，标记为未保存
  panel.querySelectorAll('input, textarea, select').forEach(function(el) {
    el.addEventListener('input', function() {
      AdminState.isDirty = true;
      const dirtyEl = document.getElementById('dirty-indicator');
      if (dirtyEl) dirtyEl.classList.remove('d-none');
    });
    el.addEventListener('change', function() {
      AdminState.isDirty = true;
      const dirtyEl = document.getElementById('dirty-indicator');
      if (dirtyEl) dirtyEl.classList.remove('d-none');
      if (el.id === 'field-card_type' && AdminState.currentCharData) {
        AdminState.currentCharData = collectVisibleEditorValues({
          ...AdminState.currentCharData,
          card_type: el.value,
        });
        renderEditPanel(AdminState.currentCharData);
        AdminState.isDirty = true;
        const nextDirtyEl = document.getElementById('dirty-indicator');
        if (nextDirtyEl) nextDirtyEl.classList.remove('d-none');
      }
    });
  });
}
