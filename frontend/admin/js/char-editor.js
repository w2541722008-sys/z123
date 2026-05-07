/**
 * char-editor.js - 编辑角色标签页逻辑
 *
 * 包含：编辑面板渲染、字段元信息、runtime_layers 编辑、
 * 好感度可视化编辑器、字段构建工具函数。
 * 依赖：utils.js, api.js, state.js, main.js（FIXED_SECTIONS 等常量）
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
  life_profile_json: { label: '👤 人生档案', desc: '角色的完整人生背景（童年、家庭、工作等），AI每轮都能看到', type: 'life_profile' },
};

const READONLY_META = {
  asset_type:         { label: '资源类型 asset_type', desc: 'character / world / hybrid 等（只读）', rows: 2 },
  embedded_format:  { label: '嵌入格式 embedded_format', desc: 'json / ccv3 / chara 等（只读）', rows: 2 },
  mock_reply_style: { label: 'mock_reply_style', desc: '占位风格文本（只读）', rows: 3 },
  import_diagnostics: { label: '导入诊断 import_diagnostics', desc: 'JSON 数组字符串（只读）', rows: 10 },
};

// runtime_layers 字段中文说明
const RL_FIELD_META = {
  primary_system_prompt: { label: '主System Prompt（深层）', desc: '从角色卡解析出的核心指令', rows: 4 },
  base_profile:          { label: '📖 角色档案（base_profile）', desc: '角色的人物背景、身份、外貌、性格等主要设定——最核心的内容在这里', rows: 20 },
  personality:           { label: '性格描述', desc: '角色性格特征', rows: 6 },
  scenario:              { label: '🎬 场景设定', desc: '故事发生的时间/地点/背景', rows: 8 },
  world_rules:           { label: '🌐 世界规则', desc: '世界观设定、规则、禁忌', rows: 10 },
  examples:              { label: '💬 示例对话', desc: '展示角色说话风格的例句', rows: 10 },
  post_history_rules:    { label: '📌 对话规则（每轮提醒）', desc: '每次对话末尾注入的格式/行为规则', rows: 6 },
  alternate_greetings:   { label: '🎭 多开场白列表', desc: '各条剧情线的开场白（用 ---分隔）', rows: 12 },
  opening_message:       { label: '开场白（深层）', desc: 'runtime里的开场白，与表字段同步', rows: 6 },
  structured_outline:    { label: '📋 结构化大纲', desc: '角色卡的结构化解析结果（JSON格式）', rows: 16 },
  world_info_before:     { label: '🌍 世界书-前置词条', desc: 'character_book 里 before_char 的词条内容', rows: 8 },
  world_info_after:      { label: '🌍 世界书-后置词条', desc: 'character_book 里 after_char 的词条内容', rows: 8 },
  conditional_entries:   { label: '⚡ 条件触发词条', desc: '关键词触发的world info词条（JSON格式）', rows: 8 },
  extension_hints:       { label: '扩展提示', desc: '其他扩展信息', rows: 4 },
};

// 字段分区（固定字段）
const FIXED_SECTIONS = [
  { title: '📋 基础展示信息', fields: ['name', 'abbr', 'subtitle', 'tags', 'opening_message'] },
  { title: '🖼️ 角色形象', fields: ['avatar_url', 'cover_url'] },
  { title: '⚙️ 系统与广场', fields: ['system_prompt', 'description', 'is_visible', 'home_priority', 'sort_order', 'card_type', 'required_plan', 'import_locked', 'affection_enabled'] },
  { title: '👤 人生档案', fields: ['life_profile_json'] },
  { title: '❤️ 好感度', fields: ['affection_rules_json'] },
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
  return `
    <div class="guide-card">
      <div class="guide-title">🧭 新手配置顺序</div>
      <div class="guide-desc">如果你现在对项目还不熟，可以直接按这个顺序做，不需要一次把所有字段都填满。</div>
      <ol class="guide-list">
        <li>先补齐：角色名、简介、主指令、开场白。</li>
        <li>再看「角色内容详情」里的 base_profile / examples，这两块最影响角色像不像真人。</li>
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
  const lenTip = (typeof val === 'string' && val.length > 0)
    ? `<span class="field-len">${val.length} 字</span>` : '';
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
  } else if (type === 'life_profile') {
    return renderLifeProfileEditor(val);
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
// 好感度可视化编辑器
// ============================================================
function renderAffectionRuleEditor(value) {
  let parsed = {};
  try {
    parsed = JSON.parse(value || '{}') || {};
  } catch (e) {
    parsed = {};
  }

  // 根据 card_type 选择事件组
  const cardType = (AdminState.currentCharData && AdminState.currentCharData.card_type) || 'intimate';
  const typeRuleMap = {
    intimate: { base: AFFECTION_BASE_RULES, all: AFFECTION_BASE_RULES, title: '❤️ 好感度规则可视化编辑器', desc: '不想直接写 JSON 的话，就在这里填。留空 = 使用系统默认值。', metricName: '好感度' },
    scenario: { base: SCENARIO_AFFECTION_RULES, all: [...AFFECTION_BASE_RULES, ...SCENARIO_AFFECTION_RULES], title: '🎭 剧情沉浸度规则可视化编辑器', desc: '剧情沙盒使用不同的沉浸度事件。留空 = 使用系统默认值。', metricName: '沉浸度' },
  };
  const typeConfig = typeRuleMap[cardType] || typeRuleMap.intimate;
  const baseRules = typeConfig.base;
  const allRules = typeConfig.all;

  const positive = baseRules.filter(([, , score]) => score >= 0);
  const negative = baseRules.filter(([, , score]) => score < 0);
  const knownKeys = new Set(allRules.map(([key]) => key));
  const customEntries = Object.entries(parsed).filter(([key]) => key !== 'enabled' && !knownKeys.has(key));

  const buildRows = (list) => list.map(([key, label, score]) => `
    <div class="affection-rule-row">
      <div class="affection-rule-name">${escHtml(label)}<span style="color:#666">（${escHtml(key)}，默认 ${score > 0 ? '+' : ''}${score}）</span></div>
      <input type="number" data-affection-key="${escHtml(key)}" value="${parsed[key] != null ? parsed[key] : ''}" placeholder="${score}" />
    </div>
  `).join('');

  const editorTitle = typeConfig.title;
  const editorDesc = typeConfig.desc;

  return `
    <div class="affection-editor">
      <div class="affection-editor-toolbar">
        <div>
          <div class="affection-editor-title">${editorTitle}</div>
          <div class="affection-editor-desc">${editorDesc}</div>
        </div>
        <label class="checkbox-group" style="margin-left:auto;">
          <input type="checkbox" id="affection-enabled-override" ${parsed.enabled === false ? '' : 'checked'} onchange="syncAffectionRulesEditor()" />
          <span>启用该角色的${typeConfig.metricName}规则</span>
        </label>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button type="button" class="btn btn-ghost" data-action="reset-affection-rules">↺ 一键恢复默认</button>
        </div>
      </div>
      <div class="affection-grid">
        <div class="affection-card">
          <h4>正向事件</h4>
          ${buildRows(positive)}
        </div>
        <div class="affection-card">
          <h4>负向事件</h4>
          ${buildRows(negative)}
        </div>
      </div>
      <div class="affection-card" style="margin-top:10px;">
        <h4>自定义事件</h4>
        <div id="affection-custom-list" class="affection-custom-list">
          ${customEntries.length ? customEntries.map(([key, score]) => `
            <div class="affection-custom-row">
              <input type="text" data-affection-custom-key value="${escHtml(key)}" placeholder="事件名，例如：study_together" />
              <input type="number" data-affection-custom-score value="${score}" placeholder="分值" />
              <button type="button" class="btn btn-ghost" data-action="remove-affection-custom-row">删除</button>
            </div>
          `).join('') : ''}
        </div>
        <div style="margin-top:10px;">
          <button type="button" class="btn btn-ghost" data-action="add-affection-custom-row">+ 新增自定义事件</button>
        </div>
      </div>
      <div class="affection-card" style="margin-top:10px;">
        <h4>⚙️ 高级配置</h4>
        <div class="affection-rule-row">
          <div class="affection-rule-name">每日${typeConfig.metricName}涨幅上限（daily_cap）<span style="color:#666">（默认 15，设为 0 = 不限制，适合剧情沙盒）</span></div>
          <input type="number" data-affection-meta="daily_cap" value="${parsed.daily_cap != null ? parsed.daily_cap : ''}" placeholder="15" min="0" max="100" oninput="syncAffectionRulesEditor()" />
        </div>
        <div class="affection-rule-row">
          <div class="affection-rule-name">允许阶段回退（allow_regression）<span style="color:#666">（默认关闭，开启后好感度下降会回退剧情阶段）</span></div>
          <select data-affection-meta="allow_regression" onchange="syncAffectionRulesEditor()">
            <option value="" ${parsed.allow_regression == null ? 'selected' : ''}>默认（关闭）</option>
            <option value="true" ${parsed.allow_regression === true ? 'selected' : ''}>✅ 开启</option>
            <option value="false" ${parsed.allow_regression === false ? 'selected' : ''}>🚫 关闭</option>
          </select>
        </div>
        <div class="affection-rule-row">
          <div class="affection-rule-name">隐藏聊天状态栏（show_bar）<span style="color:#666">（隐藏后用户看不到进度条、阶段、心情标签，增加探索未知感）</span></div>
          <select data-affection-meta="show_bar" onchange="syncAffectionRulesEditor()">
            <option value="" ${parsed.show_bar == null ? 'selected' : ''}>默认（显示）</option>
            <option value="true" ${parsed.show_bar === true ? 'selected' : ''}>👁 显示</option>
            <option value="false" ${parsed.show_bar === false ? 'selected' : ''}>🙈 隐藏</option>
          </select>
        </div>
      </div>
      <div class="affection-note">
        说明：<br />
        - 留空表示"沿用系统默认值"；<br />
        - enabled = false 表示这张角色卡关闭好感度系统；<br />
        - daily_cap = 0 表示不限制每日涨幅，适合剧情沙盒让重度玩家一次性通关；<br />
        - 自定义事件名尽量用英文下划线，例如 study_together；<br />
        - 建议分值尽量控制在 -15 到 +15 之间。
      </div>
      <div id="affection-editor-status" class="affection-status">编辑器已就绪：留空就等于使用系统默认规则。</div>
    </div>
  `;
}

function addAffectionCustomRow(key = '', score = '') {
  const list = document.getElementById('affection-custom-list');
  if (!list) return;
  const row = document.createElement('div');
  row.className = 'affection-custom-row';
  row.innerHTML = `
    <input type="text" data-affection-custom-key value="${escHtml(key)}" placeholder="事件名，例如：study_together" oninput="syncAffectionRulesEditor()" />
    <input type="number" data-affection-custom-score value="${score}" placeholder="分值" oninput="syncAffectionRulesEditor()" />
    <button type="button" class="btn btn-ghost" data-action="remove-affection-custom-row">删除</button>
  `;
  list.appendChild(row);
  syncAffectionRulesEditor();
}

function removeAffectionCustomRow(btn) {
  btn.closest('.affection-custom-row')?.remove();
  syncAffectionRulesEditor();
}

function resetAffectionRulesEditor() {
  const enabledCheckbox = document.getElementById('affection-enabled-override');
  if (enabledCheckbox) enabledCheckbox.checked = true;

  document.querySelectorAll('[data-affection-key]').forEach(input => {
    input.value = '';
  });

  const list = document.getElementById('affection-custom-list');
  if (list) list.innerHTML = '';

  syncAffectionRulesEditor();
}

function validateAffectionRulesEditor() {
  const status = document.getElementById('affection-editor-status');
  if (!status) return;

  const issues = [];
  let filledCount = 0;

  document.querySelectorAll('[data-affection-key]').forEach(input => {
    const key = input.getAttribute('data-affection-key');
    const raw = String(input.value || '').trim();
    if (!raw) return;
    filledCount += 1;
    const num = parseInt(raw, 10);
    if (Number.isNaN(num)) {
      issues.push(`${key} 不是有效数字`);
      return;
    }
    if (num > 15 || num < -15) {
      issues.push(`${key} 的分值 ${num} 超出推荐范围（-15 ~ +15）`);
    }
  });

  document.querySelectorAll('.affection-custom-row').forEach(row => {
    const key = row.querySelector('[data-affection-custom-key]')?.value?.trim() || '';
    const raw = row.querySelector('[data-affection-custom-score]')?.value?.trim() || '';
    if (!key && !raw) return;
    filledCount += 1;
    if (!/^[a-zA-Z0-9_]+$/.test(key)) {
      issues.push(`自定义事件名「${key || '（空）'}」建议只用英文、数字、下划线`);
    }
    const num = parseInt(raw, 10);
    if (raw && Number.isNaN(num)) {
      issues.push(`自定义事件「${key || '（空）'}」分值不是有效数字`);
      return;
    }
    if (raw && (num > 15 || num < -15)) {
      issues.push(`自定义事件「${key || '（空）'}」分值 ${num} 超出推荐范围（-15 ~ +15）`);
    }
  });

  if (issues.length) {
    status.className = 'affection-status warn';
    status.innerHTML = '⚠️ ' + issues.map(escHtml).join('<br />');
    return;
  }

  if (filledCount === 0) {
    status.className = 'affection-status ok';
    status.textContent = '✅ 当前没有自定义覆盖，保存后会使用系统默认好感度规则。';
    return;
  }

  status.className = 'affection-status ok';
  status.textContent = `✅ 当前已配置 ${filledCount} 项自定义好感度规则。`;
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

function syncAffectionRulesEditor() {
  const target = document.getElementById('field-affection_rules_json');
  if (!target) return;
  const obj = {};

  const enabledCheckbox = document.getElementById('affection-enabled-override');
  if (enabledCheckbox && !enabledCheckbox.checked) {
    obj.enabled = false;
  }

  document.querySelectorAll('[data-affection-key]').forEach(input => {
    const key = input.getAttribute('data-affection-key');
    const raw = String(input.value || '').trim();
    if (!raw) return;
    const num = parseInt(raw, 10);
    if (!Number.isNaN(num)) obj[key] = num;
  });

  document.querySelectorAll('.affection-custom-row').forEach(row => {
    const key = row.querySelector('[data-affection-custom-key]')?.value?.trim();
    const raw = row.querySelector('[data-affection-custom-score]')?.value?.trim();
    if (!key || !raw) return;
    const num = parseInt(raw, 10);
    if (!Number.isNaN(num)) obj[key] = num;
  });

  // 高级配置项（daily_cap, allow_regression 等）
  document.querySelectorAll('[data-affection-meta]').forEach(el => {
    const metaKey = el.getAttribute('data-affection-meta');
    if (el.tagName === 'SELECT') {
      const val = el.value;
      if (val === 'true') obj[metaKey] = true;
      else if (val === 'false') obj[metaKey] = false;
      // 空值不写入，使用系统默认
    } else if (el.type === 'number') {
      const raw = String(el.value || '').trim();
      if (raw !== '') {
        const num = parseInt(raw, 10);
        if (!Number.isNaN(num)) obj[metaKey] = num;
      }
    }
  });

  target.value = JSON.stringify(obj, null, 2);
  updateLen(target);
  validateAffectionRulesEditor();
}

// ============================================================
// 渲染编辑面板
// ============================================================
function renderEditPanel(c) {
  const panel = document.getElementById('tab-edit');
  AdminState.currentRlFields = [];

  let html = `<div class="edit-panel">
    <h2>${escHtml(c.name || '')}</h2>
    <div class="char-id">ID: ${c.id} &nbsp;|&nbsp; 类型: ${c.card_type || '?'} &nbsp;|&nbsp; 来源: ${escHtml(c.source_path || '未知')}</div>
    ${buildEditGuideHtml(c)}`;

  // 固定字段分区
  for (const section of FIXED_SECTIONS) {
    html += `<div class="section-title">${section.title}</div>`;
    for (const field of section.fields) {
      const meta = FIXED_FIELD_META[field];
      if (!meta) continue;
      if (field === 'affection_rules_json') {
        html += renderAffectionRuleEditor(c[field] ?? '{}');
      }
      html += makeFieldHtml(field, meta.label, meta.desc, meta.type, c[field] ?? '', meta);
    }
  }

  html += `<div class="section-title">📎 导入与资源（只读）</div>`;
  for (const field of READONLY_SECTION_FIELDS) {
    const meta = READONLY_META[field];
    if (!meta) continue;
    html += makeFieldHtml(field, meta.label, meta.desc, 'readonly_textarea', c[field] ?? '', meta);
  }

  // runtime_layers 字段
  const rlFields = [];
  // 核心字段始终显示（即使为空），方便用户配置
  const CORE_RL_FIELDS = ['base_profile', 'examples', 'personality', 'scenario', 'world_rules'];
  // 按预定顺序先加有数据的
  for (const rlKey of RL_DISPLAY_ORDER) {
    const fullKey = `rl__${rlKey}`;
    if (fullKey in c) rlFields.push(rlKey);
  }
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

  if (rlFields.length > 0) {
    html += `<div class="section-title">🎭 角色内容详情（runtime_layers）
      <span style="font-size:11px;color:#666;font-weight:400">— 这里才是角色的真正内容</span>
    </div>`;

    for (const rlKey of rlFields) {
      const fullKey = `rl__${rlKey}`;
      const val = c[fullKey] ?? '';
      const meta = RL_FIELD_META[rlKey];
      const label = meta?.label || rlKey;
      const desc = meta?.desc || `runtime_layers.${rlKey}`;
      const rows = meta?.rows || 6;
      if (!val && !meta) continue; // 空且无元信息的跳过
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
