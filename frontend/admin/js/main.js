/**
 * main.js - 入口逻辑 + 全局常量
 *
 * 包含：常量定义（ADVANCED_GUIDE_META、AFFECTION_BASE_RULES、FIXED_SECTIONS 等）、
 * 标签页切换、角色列表、角色选择、新建角色、保存角色、角色总览、初始化。
 * 依赖：utils.js, api.js, state.js
 * 被依赖：所有页面模块通过全局函数互相调用
 */

// ============================================================
// 高级配置各子标签页的引导说明
// ============================================================
const ADVANCED_GUIDE_META = {
  memories: {
    title: '🧠 这页怎么用：记忆条目',
    desc: '关键词被触发时，内容会被注入到AI的上下文里。它不是聊天记录，而是让AI在特定话题下"想起来"的补充设定。',
    bullets: ['优先放高频会聊到的设定，例如身份背景、关系状态、行为禁忌。', '一条记忆只说一件事，关键词要精准不要贪多。', '如果AI该知道的事却不知道，先来这里测关键词是否命中。']
  },
  categories: {
    title: '🏷️ 这页怎么用：记忆分类',
    desc: '分类只影响后台管理，不会直接改变AI输出。适合记忆条目多了之后，方便你自己整理和查找。',
    bullets: ['可按"身份背景 / 关系状态 / 世界观 / 行为禁忌"来分。', '先保证记忆内容好用，再考虑分类是否漂亮。']
  },
  greetings: {
    title: '👋 这页怎么用：开场白',
    desc: '用户首次进入或清空聊天时，AI说的第一句话。它决定第一印象，也是剧情线切换时最明显的感知点。',
    bullets: ['至少准备"陌生人 + 熟人"两档，体验会自然很多。', '不同剧情线用不同的开头，不要只是改几个字。', '如果用户一进来就出戏，优先改这里。']
  },
  storylines: {
    title: '📖 这页怎么用：剧情线',
    desc: '把角色的故事拆成几条分支（如校园线/职场线）。它本身不直接说话，但会决定用哪套开场白、后置规则和剧情事件。',
    bullets: ['没有多条分支时，可以先不配。', '一旦配了多条线，必须指定一个默认剧情线。', '剧情线名字要让用户一眼看懂差别，如"校园初遇"vs"职场重逢"。']
  },
  postrules: {
    title: '📝 这页怎么用：后置规则',
    desc: '放在历史记录之后、AI回复之前，作为最后一道约束。适合限制语气、格式和行为边界——不要把角色设定全堆在这里。',
    bullets: ['只写强约束，例如"不要跳出角色""回复保持第一人称"。', '不要把背景设定堆到这里，否则排查时会很痛苦。']
  },
  events: {
    title: '🎭 这页怎么用：剧情事件',
    desc: '好感度达到阈值时自动触发，适合做阶段转换和新内容解锁。建议同时配置"触发时的特殊对话"和"解锁的新内容"。',
    bullets: ['触发文案：事件发生时AI说的话，推进剧情用。', '解锁内容：事件触发后开放的新记忆/开场白/剧情线。', '先做2~3个关键事件，比堆很多空事件更有效。']
  },
  test: {
    title: '🧪 这页怎么用：关键词测试',
    desc: '排查工具：当你怀疑"明明写了设定为什么AI不知道"时，先到这里输入用户真实会发的消息，看能否命中记忆条目。',
    bullets: ['尽量输入真实对话，而不是把关键词堆砌在一起。', '如果测试里都命不中，聊天里大概率也不会命中。']
  }
};

// ============================================================
// 好感度基础规则表 [key, 中文名, 默认分值]
// ============================================================
const AFFECTION_BASE_RULES = [
  ['deep_conversation', '深度聊天', 4],
  ['light_chat', '日常轻聊', 1],
  ['compliment', '夸奖赞美', 2],
  ['gift', '送礼物', 6],
  ['help', '主动帮助', 3],
  ['shared_secret', '分享秘密', 5],
  ['first_meeting', '第一次打招呼', 3],
  ['comfort', '安慰对方', 3],
  ['flirt', '调情撒娇', 2],
  ['date', '约会', 5],
  ['first_hug', '第一次拥抱', 7],
  ['kiss', '亲吻', 8],
  ['confession', '表白', 10],
  ['argument', '争吵冲突', -5],
  ['rude', '粗鲁无礼', -3],
  ['ignore', '敷衍忽视', -2],
  ['lie', '说谎被发现', -4],
  ['betray', '背叛', -8],
  ['insult', '侮辱攻击', -6],
];

// ============================================================
// normalizeCharacterDetail - 展平 runtime_layers 到顶层
// ============================================================
function normalizeCharacterDetail(c) {
  const out = { ...c };
  if (c.runtime_layers && typeof c.runtime_layers === 'object') {
    for (const [k, v] of Object.entries(c.runtime_layers)) {
      out['rl__' + k] = v;
    }
  }
  out.tags = tagsToFormValue(c.tags);
  out.is_visible = c.is_visible ? 1 : 0;
  out.import_locked = c.import_locked ? 1 : 0;
  out.affection_enabled = c.affection_enabled ? 1 : 0;
  return out;
}

// ============================================================
// 标签页切换
// ============================================================
function switchTab(tab) {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });
  document.getElementById('tab-edit').style.display = tab === 'edit' ? '' : 'none';
  document.getElementById('tab-advanced').style.display = tab === 'advanced' ? '' : 'none';
  document.getElementById('tab-preview').style.display = tab === 'preview' ? '' : 'none';
  document.getElementById('tab-membership').style.display = tab === 'membership' ? '' : 'none';
  document.getElementById('tab-dashboard').style.display = tab === 'dashboard' ? '' : 'none';
  document.getElementById('tab-auditlog').style.display = tab === 'auditlog' ? '' : 'none';

  if (tab === 'advanced' && AdminState.currentCharId) {
    loadAdvancedData();
  }
  if (tab === 'preview' && AdminState.currentCharId) {
    loadPromptPreview();
  }
  if (tab === 'membership') {
    loadMembershipData();
  }
  if (tab === 'dashboard') {
    loadDashboard();
  }
  if (tab === 'auditlog') {
    loadAuditLogs();
  }
}

// ============================================================
// 角色列表
// ============================================================
function renderCharListSidebar() {
  const container = document.getElementById('char-list');
  const q = (document.getElementById('char-filter-search')?.value || '').trim().toLowerCase();
  const vis = document.getElementById('char-filter-visible')?.value || 'all';
  const typ = document.getElementById('char-filter-type')?.value || 'all';
  let chars = AdminState.allCharsCache.slice();
  if (vis === 'visible') chars = chars.filter(c => c.is_visible);
  if (vis === 'hidden') chars = chars.filter(c => !c.is_visible);
  if (typ !== 'all') chars = chars.filter(c => (c.card_type || 'intimate') === typ);
  if (q) {
    chars = chars.filter(c =>
      (c.name || '').toLowerCase().includes(q) ||
      (c.id || '').toLowerCase().includes(q) ||
      (c.abbr || '').toLowerCase().includes(q)
    );
  }
  if (!chars.length) {
    container.innerHTML = '<div class="empty-state"><div>无匹配角色</div></div>';
    return;
  }
  container.innerHTML = chars.map(c => {
    const typeBadge = { intimate: '💞对话陪伴', scenario: '🎭剧情沙盒', world: '🌐世界探索', divination: '🔮占卜形象' }[c.card_type] || c.card_type;
    const typeCls = `badge badge-${c.card_type || 'intimate'}`;
    const planBadge = c.required_plan && c.required_plan !== 'guest'
      ? `<span class="badge badge-${c.required_plan}">${formatPlanLabel(c.required_plan)}</span>`
      : '';
    const visBadge = c.is_visible
      ? '<span class="badge badge-visible">可见</span>'
      : '<span class="badge badge-hidden">隐藏</span>';
    return `<div class="char-item ${c.id === AdminState.currentCharId ? 'active' : ''}" onclick="selectChar('${c.id}')">
      <div class="char-name">${escHtml(c.name)}</div>
      <div class="char-meta">
        <span class="${typeCls}">${typeBadge}</span>
        ${planBadge}
        ${visBadge}
        <span style="color:#555">序${c.sort_order ?? 0} · 广场${c.home_priority ?? 0}</span>
      </div>
    </div>`;
  }).join('');
}

async function loadCharList() {
  const container = document.getElementById('char-list');
  try {
    const chars = await AdminAPI.apiFetch(`${AdminAPI.API}/characters`);
    AdminState.allCharsCache = chars;
    if (AdminState.currentCharId && !chars.some(c => c.id === AdminState.currentCharId)) {
      clearCurrentCharacterSelection();
    }
    if (!chars.length) {
      container.innerHTML = '<div class="empty-state"><div>暂无角色</div></div>';
      return;
    }
    renderCharListSidebar();
  } catch (e) {
    container.innerHTML = `<div class="empty-state" style="color:#f87171">加载失败：${escHtml(e.message)}</div>`;
  }
}

// ============================================================
// 选择角色 - 加载编辑面板
// ============================================================
async function selectChar(charId) {
  AdminState.currentCharId = charId;
  // 更新侧边栏高亮
  document.querySelectorAll('.char-item').forEach(el => {
    el.classList.toggle('active', el.getAttribute('onclick').includes(charId));
  });
  switchTab('edit');

  // 显示悬浮保存按钮
  const fab = document.getElementById('fab-save');
  const fabLabel = document.getElementById('fab-label');
  fab.style.display = 'flex';
  fabLabel.textContent = '保存';
  fabLabel.style.color = '#c084fc';

  const panel = document.getElementById('tab-edit');
  panel.innerHTML = '<div class="empty-state"><div class="icon">⏳</div><div>加载中...</div></div>';

  try {
    const raw = await AdminAPI.apiFetch(`${AdminAPI.API}/character/${charId}`);
    const normalized = normalizeCharacterDetail(raw);
    AdminState.currentCharData = normalized;
    renderEditPanel(normalized);
    loadCharacterSummary();
    loadPromptPreview();
  } catch (e) {
    panel.innerHTML = `<div class="empty-state" style="color:#f87171">加载失败：${e.message}</div>`;
  }
}

// ============================================================
// 清除当前角色选择
// ============================================================
function clearCurrentCharacterSelection() {
  AdminState.currentCharId = null;
  AdminState.currentCharData = null;
  AdminState.currentCharSummary = null;
  AdminState.currentPromptPreview = null;

  document.querySelectorAll('.char-item').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-edit').innerHTML = `
    <div class="empty-state">
      <div class="icon">👈</div>
      <div>从左侧选择一个角色开始编辑</div>
    </div>
  `;
  document.getElementById('advanced-empty').style.display = '';
  document.getElementById('advanced-content').style.display = 'none';
  document.getElementById('prompt-preview-content').innerHTML = '<div class="preview-box muted">请先从左侧选择角色。</div>';
  renderCharacterOverview(null);

  const fab = document.getElementById('fab-save');
  if (fab) fab.style.display = 'none';
  switchTab('edit');
}

// ============================================================
// 新建角色
// ============================================================
function openCreateCharModal() {
  // 清空表单
  document.getElementById('new-char-id').value = '';
  document.getElementById('new-char-name').value = '';
  document.getElementById('new-char-abbr').value = '';
  document.getElementById('new-char-subtitle').value = '';
  document.getElementById('new-char-description').value = '';
  document.getElementById('new-char-avatar-url').value = '';
  document.getElementById('new-char-cover-url').value = '';
  document.getElementById('new-char-system-prompt').value = '';
  document.getElementById('new-char-opening').value = '';
  document.getElementById('new-char-tags').value = '';
  document.getElementById('new-char-type').value = 'intimate';
  document.getElementById('new-char-required-plan').value = 'guest';
  document.getElementById('new-char-priority').value = '10';
  document.getElementById('new-char-visible').checked = true;
  document.getElementById('create-char-modal').style.display = 'flex';
}

function closeCreateCharModal() {
  document.getElementById('create-char-modal').style.display = 'none';
}

async function createCharacter() {
  const id = document.getElementById('new-char-id').value.trim();
  const name = document.getElementById('new-char-name').value.trim();
  const abbr = document.getElementById('new-char-abbr').value.trim();
  const subtitle = document.getElementById('new-char-subtitle').value.trim();
  const description = document.getElementById('new-char-description').value.trim();
  const avatarUrl = document.getElementById('new-char-avatar-url').value.trim();
  const coverUrl = document.getElementById('new-char-cover-url').value.trim();
  const systemPrompt = document.getElementById('new-char-system-prompt').value.trim();
  const opening = document.getElementById('new-char-opening').value.trim();
  const tagsStr = document.getElementById('new-char-tags').value.trim();
  const cardType = document.getElementById('new-char-type').value;
  const requiredPlan = document.getElementById('new-char-required-plan').value;
  const priority = parseInt(document.getElementById('new-char-priority').value) || 10;
  const isVisible = document.getElementById('new-char-visible').checked ? 1 : 0;

  // 验证必填字段
  if (!id) {
    toast('请输入角色ID');
    return;
  }
  if (!name) {
    toast('请输入角色名');
    return;
  }
  if (!systemPrompt) {
    toast('请输入主指令（System Prompt）');
    return;
  }

  // 验证ID格式（只允许英文、数字、下划线）
  if (!/^[a-zA-Z0-9_]+$/.test(id)) {
    toast('角色ID只能包含英文、数字和下划线');
    return;
  }

  // 处理标签
  const tags = tagsStr ? JSON.stringify(tagsStr.split(',').map(t => t.trim()).filter(t => t)) : '[]';

  const data = {
    id,
    name,
    abbr: abbr || name,
    subtitle,
    description,
    avatar_url: avatarUrl,
    cover_url: coverUrl,
    system_prompt: systemPrompt,
    opening_message: opening,
    tags,
    card_type: cardType,
    required_plan: requiredPlan,
    home_priority: priority,
    is_visible: isVisible,
  };

  try {
    await AdminAPI.apiFetch(`${AdminAPI.API}/characters`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
    closeCreateCharModal();
    toast('✅ 角色创建成功！');
    await loadCharList();
    await selectChar(id);
  } catch (e) {
    toast('创建失败：' + e.message);
  }
}

// ============================================================
// 保存角色
// ============================================================
async function saveChar() {
  if (!AdminState.currentCharId) return;

  const updates = {};

  try {
    for (const section of FIXED_SECTIONS) {
      for (const field of section.fields) {
        const el = document.getElementById(`field-${field}`);
        if (!el) continue;
        if (field === 'tags') {
          updates.tags = formTagsToServer(el.value);
          continue;
        }
        if (field === 'affection_rules_json') {
          syncAffectionRulesEditor();
          updates[field] = validateJsonString(el.value, '好感度规则');
          continue;
        }
        let val = el.value;
        if (FIXED_FIELD_META[field]?.type === 'number') val = parseInt(val, 10) || 0;
        if (['is_visible', 'import_locked', 'affection_enabled'].includes(field)) val = parseInt(val, 10);
        updates[field] = val;
      }
    }

    for (const rlKey of AdminState.currentRlFields) {
      const el = document.getElementById(`field-rl__${rlKey}`);
      if (!el) continue;
      updates[`rl__${rlKey}`] = el.value;
    }
  } catch (e) {
    toast(e.message || String(e));
    return;
  }

  const statusEl = document.getElementById('save-status');
  const fabLabel = document.getElementById('fab-label');
  if (statusEl) { statusEl.textContent = '保存中...'; statusEl.className = 'save-status'; }
  if (fabLabel) { fabLabel.textContent = '保存中…'; fabLabel.style.color = '#888'; }

  try {
    await AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}`, {
      method: 'POST',
      body: JSON.stringify({ updates }),
    });
    const refreshed = await AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}`);
    AdminState.currentCharData = normalizeCharacterDetail(refreshed);
    if (statusEl) { statusEl.textContent = '✅ 保存成功！'; statusEl.className = 'save-status ok'; }
    if (fabLabel) { fabLabel.textContent = '✅ 已保存'; fabLabel.style.color = '#4ade80'; setTimeout(()=>{ fabLabel.textContent='保存'; fabLabel.style.color='#c084fc'; }, 2500); }
    toast('保存成功！修改立即生效（无需重启）');
    loadCharList();
    loadCharacterSummary();
    loadPromptPreview();
  } catch (e) {
    if (statusEl) { statusEl.textContent = `❌ 保存失败：${e.message}`; statusEl.className = 'save-status err'; }
    if (fabLabel) { fabLabel.textContent = '❌ 失败'; fabLabel.style.color = '#f87171'; setTimeout(()=>{ fabLabel.textContent='保存'; fabLabel.style.color='#c084fc'; }, 3000); }
    toast('保存失败：' + e.message);
  }
}

// ============================================================
// 删除角色
// ============================================================
async function deleteCurrentCharacter() {
  if (!AdminState.currentCharId) return;

  const characterId = AdminState.currentCharId;
  const characterName = AdminState.currentCharData?.name || characterId;
  const confirmMsg =
    `确定要删除角色「${characterName}」吗？\n\n` +
    `会同时删除该角色的记忆、开场白、剧情线、剧情事件以及关联聊天记录，此操作不可撤销。`;
  if (!confirm(confirmMsg)) return;

  try {
    await AdminAPI.apiFetch(`${AdminAPI.API}/character/${characterId}`, { method: 'DELETE' });
    clearCurrentCharacterSelection();
    await loadCharList();
    toast(`已删除角色：${characterName}`);
  } catch (e) {
    toast('删除失败：' + e.message);
  }
}

// ============================================================
// 角色总览 / 健康检查
// ============================================================
function renderCharacterOverview(summary) {
  const container = document.getElementById('char-overview');
  if (!summary) {
    container.style.display = 'none';
    container.innerHTML = '';
    return;
  }

  const stats = summary.stats || {};
  const warnings = Array.from(new Set([...(summary.warnings || []), ...buildExtraWarnings(summary)]));
  const completeness = summary.completeness ?? 0;
  const scoreClass = completeness >= 80 ? 'ok' : 'warn';
  const checklist = buildChecklist(summary);
  const nextActions = checklist.filter(x => !x.ok).slice(0, 3);
  const activeMemories = stats.active_memories ?? stats.memories ?? 0;
  const activeGreetings = stats.active_greetings ?? stats.greetings ?? 0;
  const activeStorylines = stats.active_storylines ?? stats.storylines ?? 0;
  const activeEvents = stats.active_events ?? stats.events ?? 0;

  container.innerHTML = `
    <div class="overview-card">
      <div class="overview-title">📊 角色总览</div>
      <div class="overview-hero">
        <div>
          <div class="overview-name">${escHtml(summary.name || AdminState.currentCharData?.name || AdminState.currentCharId || '')}</div>
          <div class="overview-subtitle">${escHtml(summary.subtitle || AdminState.currentCharData?.subtitle || '补齐基础说明、开场白、剧情线与记忆后，这个角色会更易运营。')}</div>
        </div>
        <div class="overview-score">
          <div class="score-value">${completeness}</div>
          <div class="score-label">配置完整度</div>
        </div>
      </div>
      <div class="overview-meta">
        <div class="overview-stat">
          <div class="stat-label">记忆条目</div>
          <div class="stat-value">${activeMemories}</div>
          <div class="stat-sub">启用中 / 总数 ${stats.memories || 0}</div>
        </div>
        <div class="overview-stat">
          <div class="stat-label">开场白</div>
          <div class="stat-value">${activeGreetings}</div>
          <div class="stat-sub">覆盖 ${stats.greeting_phase_coverage || 0} 个阶段</div>
        </div>
        <div class="overview-stat">
          <div class="stat-label">剧情线</div>
          <div class="stat-value">${activeStorylines}</div>
          <div class="stat-sub">默认剧情线 ${summary.default_storyline_id ? '已设置' : '未设置'}</div>
        </div>
        <div class="overview-stat">
          <div class="stat-label">剧情事件</div>
          <div class="stat-value">${activeEvents}</div>
          <div class="stat-sub">缺解锁 ${stats.empty_unlock_events || 0} / 缺文案 ${stats.empty_event_content_events || 0}</div>
        </div>
      </div>
    </div>
    <div class="health-card">
      <div class="health-title">🩺 配置健康检查</div>
      <div class="health-list">
        ${warnings.length ? warnings.map(item => `<div class="health-item ${scoreClass}">⚠️ ${escHtml(item)}</div>`).join('') : '<div class="health-item ok">✅ 目前没有明显配置缺口，可以继续做精细化优化。</div>'}
      </div>
      <div class="diagnostic-grid">
        ${checklist.map(item => `
          <div class="diagnostic-item ${item.ok ? 'ok' : 'warn'}">
            <div class="title">${item.ok ? '✅ ' : '⚠️ '}${escHtml(item.title)}</div>
            <div>${escHtml(item.text)}</div>
          </div>
        `).join('')}
      </div>
      <div class="quick-actions">
        ${nextActions.length ? nextActions.map(item => `<span class="item-badge">下一步：${escHtml(item.title)}</span>`).join('') : '<span class="item-badge active">当前这张卡已经比较完整了</span>'}
      </div>
    </div>
  `;
  container.style.display = '';
}

async function loadCharacterSummary() {
  if (!AdminState.currentCharId) return;
  try {
    const summary = await AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}/config-summary`);
    AdminState.currentCharSummary = summary;
    renderCharacterOverview(summary);
  } catch (e) {
    AdminState.currentCharSummary = null;
    document.getElementById('char-overview').innerHTML = `
      <div class="health-card" style="grid-column:1/-1">
        <div class="health-title">🩺 配置健康检查</div>
        <div class="health-item warn">加载角色总览失败：${escHtml(e.message)}</div>
      </div>
    `;
    document.getElementById('char-overview').style.display = '';
  }
}

// ============================================================
// 健康检查辅助
// ============================================================
function parseAffectionRules(raw) {
  const text = String(raw || '').trim();
  if (!text) return null;
  try { return JSON.parse(text); } catch (e) { return null; }
}

function hasUsableAffectionRules(raw) {
  const parsed = parseAffectionRules(raw);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') return false;
  return Object.values(parsed).some(value => {
    if (value == null) return false;
    if (Array.isArray(value)) return value.length > 0;
    if (typeof value === 'object') return Object.keys(value).length > 0;
    if (typeof value === 'string') return value.trim() !== '';
    return true;
  });
}

function buildExtraWarnings(summary) {
  const extra = [];
  const stats = summary?.stats || {};
  const storylines = AdminState.advancedData.storylines || [];
  const greetings = AdminState.advancedData.greetings || [];
  const phases = new Set(greetings.filter(x => x.is_active).map(x => x.story_phase));
  const activeMemories = stats.active_memories ?? stats.memories ?? 0;
  const activeGreetings = stats.active_greetings ?? stats.greetings ?? 0;
  const activePostRules = stats.active_post_rules ?? stats.post_rules ?? 0;
  const phaseCoverage = stats.greeting_phase_coverage ?? phases.size;
  const affectionEnabled = AdminState.currentCharData?.affection_enabled === 1 || AdminState.currentCharData?.affection_enabled === '1';
  const hasAffectionRules = hasUsableAffectionRules(AdminState.currentCharData?.affection_rules_json);

  if (affectionEnabled && !hasAffectionRules) {
    extra.push('已启用好感度系统，但好感度规则还是空的。');
  }
  if (activeMemories > 0 && activeMemories < 3) {
    extra.push('当前启用中的记忆条目偏少，建议至少保留 3 条高频记忆。');
  }
  if (activeGreetings > 0 && phaseCoverage > 0 && phaseCoverage < 2) {
    extra.push('开场白阶段比较单一，建议至少覆盖 2 个关系阶段。');
  }
  if ((stats.post_rules || 0) > 0 && activePostRules === 0) {
    extra.push('后置规则虽然配置了，但目前全部处于禁用状态。');
  }
  if (storylines.length > 0 && !summary.default_storyline_id) {
    extra.push('已有剧情线，但还没有设置默认剧情线。');
  }
  if ((stats.events || 0) > 0 && (stats.storylines || 0) === 0) {
    extra.push('已经配置剧情事件，但没有剧情线，后续扩展会不方便。');
  }
  if ((stats.empty_unlock_events || 0) > 0) {
    extra.push(`有 ${stats.empty_unlock_events} 个剧情事件还没有配置任何解锁内容。`);
  }
  if ((stats.empty_event_content_events || 0) > 0) {
    extra.push(`有 ${stats.empty_event_content_events} 个剧情事件还没有触发文案，剧情衔接可能生硬。`);
  }
  return extra;
}

function buildChecklist(summary) {
  const stats = summary?.stats || {};
  const greetings = AdminState.advancedData.greetings || [];
  const storylines = AdminState.advancedData.storylines || [];
  const memories = AdminState.advancedData.memories || [];
  const events = AdminState.advancedData.events || [];
  const phases = new Set(greetings.filter(x => x.is_active).map(x => x.story_phase));
  const activeMemories = stats.active_memories ?? memories.filter(x => x.is_active).length;
  const activeGreetings = stats.active_greetings ?? greetings.filter(x => x.is_active).length;
  const activeStorylines = stats.active_storylines ?? storylines.filter(x => x.is_active).length;
  const activePostRules = stats.active_post_rules ?? (AdminState.advancedData.postRules || []).filter(x => x.is_active).length;
  const activeEvents = stats.active_events ?? events.filter(x => x.is_active).length;
  const phaseCoverage = stats.greeting_phase_coverage ?? phases.size;
  const emptyUnlockEvents = stats.empty_unlock_events ?? events.filter(e => !(splitCsvIds(e.unlocked_memory_ids).length || splitCsvIds(e.unlocked_greeting_ids).length || e.unlocked_storyline_id)).length;
  const emptyEventContentEvents = stats.empty_event_content_events ?? events.filter(e => !String(e.event_content || '').trim()).length;
  const isWorldCard = (AdminState.currentCharData?.card_type || 'intimate') === 'world';
  const affectionEnabled = AdminState.currentCharData?.affection_enabled === 1 || AdminState.currentCharData?.affection_enabled === '1';
  const hasAffectionRules = hasUsableAffectionRules(AdminState.currentCharData?.affection_rules_json);

  return [
    {
      ok: Boolean((AdminState.currentCharData?.name || '').trim() && (AdminState.currentCharData?.system_prompt || '').trim()),
      title: '基础资料',
      text: (AdminState.currentCharData?.name || '').trim() && (AdminState.currentCharData?.system_prompt || '').trim()
        ? '角色名和主指令都已填写。'
        : '建议先补齐角色名和主指令，这是最基础的两项。'
    },
    {
      ok: activeMemories >= 3,
      title: '记忆条目',
      text: activeMemories >= 3
        ? `当前已有 ${activeMemories} 条启用中的记忆，基础注入够用了。`
        : `当前只有 ${activeMemories || 0} 条启用中的记忆（总数 ${stats.memories || 0}），建议至少准备 3 条常用触发内容。`
    },
    {
      ok: isWorldCard || phaseCoverage >= 2,
      title: '开场白阶段覆盖',
      text: isWorldCard
        ? '世界探索型角色对多阶段开场白要求较低。'
        : (phaseCoverage >= 2
            ? `已覆盖 ${phaseCoverage} 个关系阶段。`
            : `当前只有 ${activeGreetings || 0} 条启用中的开场白，建议至少覆盖"陌生人 + 熟人"两档。`)
    },
    {
      ok: activeStorylines === 0 || Boolean(summary.default_storyline_id),
      title: '默认剧情线',
      text: activeStorylines === 0
        ? '目前还没配剧情线，可以暂时先不配。'
        : (summary.default_storyline_id ? '已设置默认剧情线。' : '已有剧情线，但还没指定默认剧情线。')
    },
    {
      ok: activeEvents === 0 || (emptyUnlockEvents === 0 && emptyEventContentEvents === 0),
      title: '剧情事件完整度',
      text: activeEvents === 0
        ? '还没有剧情事件，后续可以按好感阈值逐步添加。'
        : ((emptyUnlockEvents === 0 && emptyEventContentEvents === 0)
            ? '所有启用中的剧情事件都具备解锁内容和触发文案。'
            : `当前还有 ${emptyUnlockEvents} 个事件缺解锁内容、${emptyEventContentEvents} 个事件缺触发文案。`)
    },
    {
      ok: (stats.post_rules || 0) === 0 || activePostRules > 0,
      title: '后置规则可用性',
      text: (stats.post_rules || 0) === 0
        ? '目前还没有配置后置规则。'
        : (activePostRules > 0
            ? `已有 ${activePostRules} 条启用中的后置规则。`
            : '虽然后置规则已配置，但现在全部是禁用状态。')
    },
    {
      ok: !affectionEnabled || hasAffectionRules,
      title: '好感度规则',
      text: !affectionEnabled
        ? '当前角色未启用好感度系统。'
        : (hasAffectionRules
            ? '好感度系统已启用，且已有有效规则配置。'
            : '好感度已启用，但规则还是空的。')
    }
  ];
}

// ============================================================
// 初始化
// ============================================================
AdminAPI.bootstrapAdminPage().then(ok => {
  if (ok) {
    loadCharList();
  }
});
