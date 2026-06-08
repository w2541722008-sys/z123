/**
 * char-advanced.js - 世界书 + 剧情标签页的所有逻辑
 * 重构版：取消子标签，改为世界书/剧情两个顶级标签内的区块布局
 */

// ============================================================
// 阶段标签 — 根据 card_type 动态切换
// ============================================================
const INTIMATE_PHASE_LABELS = { stranger: '陌生人', acquaintance: '熟人', friend: '朋友', lover: '恋人' };
const SCENARIO_PHASE_LABELS = { stranger: '初入', acquaintance: '探索', friend: '深入', lover: '终章' };
const INTIMATE_PHASE_EMOJIS = { stranger: '😐', acquaintance: '🙂', friend: '😊', lover: '❤️' };
const SCENARIO_PHASE_EMOJIS = { stranger: '🌅', acquaintance: '🔍', friend: '⚔️', lover: '🏆' };

const PHASE_LABEL_MAPS = {
  intimate: INTIMATE_PHASE_LABELS,
  scenario: SCENARIO_PHASE_LABELS,
};
const PHASE_EMOJI_MAPS = {
  intimate: INTIMATE_PHASE_EMOJIS,
  scenario: SCENARIO_PHASE_EMOJIS,
};

function getPhaseLabels() {
  const ct = AdminState.currentCharData?.card_type || 'intimate';
  return PHASE_LABEL_MAPS[ct] || INTIMATE_PHASE_LABELS;
}
function getPhaseEmoji(phase) {
  const ct = AdminState.currentCharData?.card_type || 'intimate';
  const emojis = PHASE_EMOJI_MAPS[ct] || INTIMATE_PHASE_EMOJIS;
  return emojis[phase] || '';
}
function getPhaseLabel(phase) {
  return getPhaseLabels()[phase] || phase;
}
function updatePhaseSelect(selectId, currentValue) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  const ct = AdminState.currentCharData?.card_type || 'intimate';
  const labels = PHASE_LABEL_MAPS[ct] || INTIMATE_PHASE_LABELS;
  const emojis = PHASE_EMOJI_MAPS[ct] || INTIMATE_PHASE_EMOJIS;
  const hasAllOption = sel.querySelector('option[value=""]');
  sel.innerHTML = '';
  let options = hasAllOption ? '<option value="">全部阶段</option>' : '';
  for (const [val, label] of Object.entries(labels)) {
    options += `<option value="${val}">${emojis[val]||''} ${label}</option>`;
  }
  sel.innerHTML = options;
  sel.value = currentValue || 'stranger';
}
function updatePhaseButtons() {
  const container = document.getElementById('greeting-phase-buttons');
  if (!container) return;
  const ct = AdminState.currentCharData?.card_type || 'intimate';
  const labels = PHASE_LABEL_MAPS[ct] || INTIMATE_PHASE_LABELS;
  const emojis = PHASE_EMOJI_MAPS[ct] || INTIMATE_PHASE_EMOJIS;
  container.innerHTML = `
    <button class="phase-btn active" data-action="filter-greetings" data-phase="all">全部</button>
    ${Object.entries(labels).map(([val, label]) => `<button class="phase-btn" data-action="filter-greetings" data-phase="${val}">${emojis[val]||''} ${label}</button>`).join('')}
  `;
}

// ============================================================
// 通用 CRUD 辅助
// ============================================================
function closeModal(modalId) { document.getElementById(modalId).style.display = 'none'; }
function cleanStorylineId(raw) { if (!raw) return null; const n = raw.trim(); return n || null; }
function sameId(a, b) { return String(a) === String(b); }
function getScoreLabel() {
  return AdminState.currentCharData?.card_type === 'scenario' ? '沉浸度' : '好感度';
}
function validateStoryline(rawStorylineId, inactiveMsg) {
  if (!rawStorylineId) return null;
  const storyline = getStorylineById(rawStorylineId);
  if (!storyline) return '当前选择的剧情线不存在，请重新选择';
  if (!storyline.is_active) return (inactiveMsg || '当前选择的剧情线已禁用');
  return null;
}
async function crudSave(endpoint, data, modalId, idValue) {
  const url = idValue
    ? `${AdminAPI.API}/character/${AdminState.currentCharId}${endpoint}/${idValue}`
    : `${AdminAPI.API}/character/${AdminState.currentCharId}${endpoint}`;
  try {
    await AdminAPI.apiFetch(url, { method: idValue ? 'PUT' : 'POST', body: JSON.stringify(data) });
    closeModal(modalId); toast('保存成功'); loadAdvancedData();
  } catch (e) { toast('保存失败：' + e.message); }
}
async function crudDelete(endpoint, idValue, modalId, confirmMsg) {
  if (!idValue) return;
  const confirmed = await showConfirm(confirmMsg || '确定删除？', '删除确认');
  if (!confirmed) return;
  try {
    await AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}${endpoint}/${idValue}`, { method: 'DELETE' });
    closeModal(modalId); toast('删除成功'); loadAdvancedData();
  } catch (e) { toast('删除失败：' + e.message); }
}

// ============================================================
// 加载高级配置数据
// ============================================================
async function loadAdvancedData() {
  if (!AdminState.currentCharId) return;
  const worldinfoEmpty = document.getElementById('worldinfo-empty');
  const worldinfoContent = document.getElementById('worldinfo-content');
  if (worldinfoEmpty) worldinfoEmpty.style.display = 'none';
  if (worldinfoContent) worldinfoContent.style.display = '';
  const storyEmpty = document.getElementById('story-empty');
  const storyContent = document.getElementById('story-content');
  if (storyEmpty) storyEmpty.style.display = 'none';
  if (storyContent) storyContent.style.display = '';
  try {
    const [memories, categories, greetings, storylines, postRules, events] = await Promise.all([
      AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}/memories`),
      AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}/memory-categories`),
      AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}/greetings`),
      AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}/storylines`),
      AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}/post-rules`),
      AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}/story-events`),
    ]);
    AdminState.advancedData = { memories, categories, greetings, storylines, postRules, events };
    updatePhaseButtons();
    renderMemories(); updateMemoryCategoryFilter(); renderCategories();
    renderGreetings(); renderStorylines(); renderPostRules(); renderEvents();
    updateStorylineOptions(); renderWorldInfoGuide(); renderStoryGuide();
  } catch (e) { toast('加载配置失败：' + e.message); }
}

// ============================================================
// 引导卡片
// ============================================================
function renderWorldInfoGuide() {
  const card = document.getElementById('worldinfo-guide-card');
  if (!card) return;
  card.innerHTML = `<div class="guide-title">🌍 世界书配置指南</div>
    <div class="guide-desc">世界书（World Info）是关键词触发的知识注入系统。当用户消息包含设定关键词时，对应内容会被临时注入AI上下文。</div>
    <ol class="guide-list"><li>先建几个记忆分类，方便后续归类。</li><li>添加 3 条以上高频记忆条目，关键词要精准不要贪多。</li><li>用关键词测试面板排查问题。</li></ol>
    <div class="guide-chip-row"><span class="guide-chip">关键词要精准</span><span class="guide-chip">一条记忆说一件事</span><span class="guide-chip">先用测试排查</span></div>`;
}
function renderStoryGuide() {
  const card = document.getElementById('story-guide-card');
  if (!card) return;
  const scoreLabel = getScoreLabel();
  card.innerHTML = `<div class="guide-title">📖 剧情配置指南</div>
    <div class="guide-desc">剧情系统由剧情线、开场白、剧情事件、后置规则四部分组成，相互配合推进故事。</div>
    <ol class="guide-list"><li>先建剧情线，至少设一条为默认。</li><li>为每个关系阶段准备至少 1 条开场白。</li><li>剧情事件按${scoreLabel}阈值触发，先做 2~3 个关键事件。</li><li>后置规则只写强约束。</li></ol>
    <div class="guide-chip-row"><span class="guide-chip">剧情线先建</span><span class="guide-chip">开场白分阶段</span><span class="guide-chip">事件不要贪多</span></div>`;
}

// ============================================================
// 辅助查询函数
// ============================================================
function memoryCategoryName(categoryId) {
  if (categoryId == null) return '';
  const c = (AdminState.advancedData.categories || []).find(x => sameId(x.id, categoryId));
  return c ? c.name : ('#' + categoryId);
}
function getMemoryNameById(id) {
  const item = (AdminState.advancedData.memories || []).find(x => sameId(x.id, id));
  return item ? (item.keywords || item.comment || `记忆#${id}`) : `记忆#${id}`;
}
function getGreetingNameById(id) {
  const item = (AdminState.advancedData.greetings || []).find(x => sameId(x.id, id));
  return item ? `${getPhaseLabel(item.story_phase)} / ${item.mood || 'neutral'}` : `开场白#${id}`;
}
function getStorylineNameById(id) {
  const item = (AdminState.advancedData.storylines || []).find(x => sameId(x.id, id));
  return item ? (item.name || `剧情线#${id}`) : `剧情线#${id}`;
}
function getStorylineById(id) {
  return (AdminState.advancedData.storylines || []).find(x => sameId(x.id, id)) || null;
}
function getMemoryMode(m) {
  if (m.constant) return 'constant';
  if (!m.selective) return 'always';
  return 'keyword';
}
function getMemoryModeLabel(mode) {
  return { keyword: '🔑关键词', constant: '🔄常驻', always: '📋始终' }[mode] || mode;
}

// ============================================================
// 记忆条目管理
// ============================================================
function updateMemoryCategoryOptions(selectedId) {
  const sel = document.getElementById('memory-category');
  const cats = AdminState.advancedData.categories || [];
  sel.innerHTML = '<option value="">不分类</option>' + cats.map(c => `<option value="${c.id}">${escHtml(c.name)}</option>`).join('');
  sel.value = selectedId != null && selectedId !== '' ? String(selectedId) : '';
}
function updateMemoryCategoryFilter() {
  const sel = document.getElementById('memory-filter-category');
  if (!sel) return;
  const cats = AdminState.advancedData.categories || [];
  const current = sel.value;
  sel.innerHTML = '<option value="all">全部分类</option>' + cats.map(c => `<option value="${c.id}">${escHtml(c.name)}</option>`).join('');
  sel.value = current || 'all';
}
function renderMemories() {
  const container = document.getElementById('memories-list');
  const q = AdminState.memorySearchQuery;
  const catFilter = AdminState.memoryFilterCategory;
  const statusFilter = AdminState.memoryFilterStatus;
  const modeFilter = AdminState.memoryFilterMode;
  let memories = (AdminState.advancedData.memories || []).filter(m => {
    if (q && !(m.keywords||'').toLowerCase().includes(q) && !(m.content||'').toLowerCase().includes(q) && !(m.comment||'').toLowerCase().includes(q)) return false;
    if (catFilter && catFilter !== 'all' && String(m.category_id) !== String(catFilter)) return false;
    if (statusFilter === 'active' && !m.is_active) return false;
    if (statusFilter === 'inactive' && m.is_active) return false;
    if (modeFilter && modeFilter !== 'all' && getMemoryMode(m) !== modeFilter) return false;
    return true;
  });
  if (!memories.length) { container.innerHTML = '<div class="no-results">暂无匹配的记忆条目</div>'; return; }
  container.innerHTML = memories.map(m => {
    const catLabel = memoryCategoryName(m.category_id);
    const mode = getMemoryMode(m);
    const catBadge = catLabel ? `<span class="item-badge" style="border:1px solid #5b21b6;color:#c084fc;">${escHtml(catLabel)}</span>` : '';
    return `<div class="item-card ${m.is_active ? '' : 'inactive'}">
      <div class="item-header">
        <span class="item-title">${escHtml(m.keywords)}</span>
        <div class="item-badges">
          <span class="item-badge mode-${mode}">${getMemoryModeLabel(mode)}</span>
          ${catBadge}
          <span class="item-badge ${m.is_active ? 'active' : ''}">${m.is_active ? '启用' : '禁用'}</span>
          <span class="item-badge">${m.position === 'before' ? '前置' : '后置'}</span>
          ${m.sticky > 0 ? `<span class="item-badge sticky">持续${m.sticky}轮</span>` : ''}
          ${m.cooldown > 0 ? `<span class="item-badge cooldown">冷却${m.cooldown}轮</span>` : ''}
        </div>
      </div>
      <div class="item-content">${escHtml(m.content.substring(0, 120))}${m.content.length > 120 ? '...' : ''}</div>
      <div class="item-footer">
        <span class="item-meta">优先级 ${m.priority}${m.comment ? ' · ' + escHtml(m.comment) : ''}</span>
        <div class="item-actions"><button class="item-btn edit" data-action="edit-memory" data-id="${escHtml(String(m.id))}">编辑</button></div>
      </div></div>`;
  }).join('');
}
function openMemoryModal() {
  document.getElementById('memory-id').value = '';
  document.getElementById('memory-keywords').value = '';
  document.getElementById('memory-trigger-logic').value = 'any';
  document.getElementById('memory-content').value = '';
  document.getElementById('memory-position').value = 'before';
  document.getElementById('memory-priority').value = 100;
  document.getElementById('memory-comment').value = '';
  document.getElementById('memory-is-active').checked = true;
  document.getElementById('memory-trigger-mode').value = 'keyword';
  document.getElementById('memory-sticky').value = 0;
  document.getElementById('memory-cooldown').value = 0;
  document.getElementById('memory-mode-hint').textContent = '关键词触发：用户消息包含关键词时才注入此条目。';
  updateMemoryCategoryOptions(null);
  document.getElementById('memory-modal-title').textContent = '新增记忆条目';
  document.getElementById('memory-delete-btn').style.display = 'none';
  document.getElementById('memory-modal').style.display = 'flex';
}
function editMemory(id) {
  const m = AdminState.advancedData.memories.find(x => sameId(x.id, id));
  if (!m) return;
  const mode = getMemoryMode(m);
  document.getElementById('memory-id').value = m.id;
  document.getElementById('memory-keywords').value = m.keywords;
  document.getElementById('memory-trigger-logic').value = m.trigger_logic || 'any';
  document.getElementById('memory-content').value = m.content;
  document.getElementById('memory-position').value = m.position;
  document.getElementById('memory-priority').value = m.priority;
  document.getElementById('memory-comment').value = m.comment || '';
  document.getElementById('memory-is-active').checked = m.is_active;
  document.getElementById('memory-trigger-mode').value = mode;
  document.getElementById('memory-sticky').value = m.sticky || 0;
  document.getElementById('memory-cooldown').value = m.cooldown || 0;
  const hints = { keyword: '关键词触发：用户消息包含关键词时才注入此条目。', constant: '每轮常驻：不需要关键词匹配，每轮对话都会注入。Sticky/Cooldown不适用。', always: '始终注入：无需关键词匹配。适合背景设定类内容。' };
  document.getElementById('memory-mode-hint').textContent = hints[mode] || '';
  updateMemoryCategoryOptions(m.category_id);
  document.getElementById('memory-modal-title').textContent = '编辑记忆条目';
  document.getElementById('memory-delete-btn').style.display = '';
  document.getElementById('memory-modal').style.display = 'flex';
}
function closeMemoryModal() { closeModal('memory-modal'); }
async function saveMemory() {
  const id = document.getElementById('memory-id').value;
  const mode = document.getElementById('memory-trigger-mode').value;
  const selective = mode === 'always' ? 0 : 1;
  const constant = mode === 'constant' ? 1 : 0;
  await crudSave('/memories', {
    keywords: document.getElementById('memory-keywords').value,
    trigger_logic: document.getElementById('memory-trigger-logic').value,
    content: document.getElementById('memory-content').value,
    position: document.getElementById('memory-position').value,
    priority: parseInt(document.getElementById('memory-priority').value) || 100,
    comment: document.getElementById('memory-comment').value,
    is_active: document.getElementById('memory-is-active').checked ? 1 : 0,
    category_id: cleanStorylineId(document.getElementById('memory-category').value),
    selective, constant,
    sticky: parseInt(document.getElementById('memory-sticky').value) || 0,
    cooldown: parseInt(document.getElementById('memory-cooldown').value) || 0,
  }, 'memory-modal', id);
}
async function deleteMemory() {
  await crudDelete('/memories', document.getElementById('memory-id').value, 'memory-modal', '确定要删除这个记忆条目吗？');
}

// ============================================================
// 开场白管理
// ============================================================
function renderGreetings() {
  const container = document.getElementById('greetings-list');
  let greetings = AdminState.advancedData.greetings;
  if (AdminState.currentGreetingFilter !== 'all') greetings = greetings.filter(g => g.story_phase === AdminState.currentGreetingFilter);
  if (!greetings.length) { container.innerHTML = '<div class="no-results">该阶段暂无开场白</div>'; return; }
  const phaseNames = getPhaseLabels();
  const moodEmojis = { neutral: '😐', happy: '😊', warm: '🥰', melting: '💗', cold: '🧊', angry: '😠', sad: '😢', shy: '😳', surprised: '😲' };
  container.innerHTML = greetings.map(g => `<div class="item-card ${g.is_active ? '' : 'inactive'}">
    <div class="item-header"><div class="item-badges">
      <span class="item-badge phase-${g.story_phase}">${getPhaseEmoji(g.story_phase)} ${phaseNames[g.story_phase]||g.story_phase}</span>
      <span class="item-badge">${moodEmojis[g.mood]||''} ${g.mood}</span>
      <span class="item-badge ${g.is_active?'active':''}">${g.is_active?'启用':'禁用'}</span></div>
      <span class="item-meta">优先级 ${g.priority}</span></div>
    <div class="item-content">${escHtml(g.content.substring(0,150))}${g.content.length>150?'...':''}</div>
    <div class="item-footer"><span class="item-meta">使用 ${g.use_count||0} 次</span>
      <div class="item-actions"><button class="item-btn edit" data-action="edit-greeting" data-id="${escHtml(String(g.id))}">编辑</button></div></div></div>`).join('');
}
function filterGreetings(phase) {
  AdminState.currentGreetingFilter = phase;
  document.querySelectorAll('.phase-btn').forEach(b => b.classList.toggle('active', b.dataset.phase === phase));
  renderGreetings();
}
function openGreetingModal() {
  document.getElementById('greeting-id').value = ''; document.getElementById('greeting-content').value = '';
  updatePhaseSelect('greeting-phase', 'stranger');
  document.getElementById('greeting-mood').value = 'neutral';
  document.getElementById('greeting-priority').value = 100; document.getElementById('greeting-storyline').value = '';
  document.getElementById('greeting-is-active').checked = true;
  document.getElementById('greeting-modal-title').textContent = '新增开场白';
  document.getElementById('greeting-delete-btn').style.display = 'none';
  document.getElementById('greeting-modal').style.display = 'flex';
}
function editGreeting(id) {
  const g = AdminState.advancedData.greetings.find(x => sameId(x.id, id)); if (!g) return;
  document.getElementById('greeting-id').value = g.id; document.getElementById('greeting-content').value = g.content;
  updatePhaseSelect('greeting-phase', g.story_phase);
  document.getElementById('greeting-mood').value = g.mood;
  document.getElementById('greeting-priority').value = g.priority; document.getElementById('greeting-storyline').value = g.storyline_id||'';
  document.getElementById('greeting-is-active').checked = g.is_active;
  document.getElementById('greeting-modal-title').textContent = '编辑开场白';
  document.getElementById('greeting-delete-btn').style.display = '';
  document.getElementById('greeting-modal').style.display = 'flex';
}
function closeGreetingModal() { closeModal('greeting-modal'); }
async function saveGreeting() {
  const id = document.getElementById('greeting-id').value;
  const rawStorylineId = document.getElementById('greeting-storyline').value;
  const err = validateStoryline(rawStorylineId); if (err) { toast(err); return; }
  await crudSave('/greetings', { content: document.getElementById('greeting-content').value, story_phase: document.getElementById('greeting-phase').value, mood: document.getElementById('greeting-mood').value, priority: parseInt(document.getElementById('greeting-priority').value)||100, storyline_id: cleanStorylineId(rawStorylineId), is_active: document.getElementById('greeting-is-active').checked?1:0 }, 'greeting-modal', id);
}
async function deleteGreeting() { await crudDelete('/greetings', document.getElementById('greeting-id').value, 'greeting-modal', '确定要删除这个开场白吗？'); }

// ============================================================
// 剧情线管理
// ============================================================
function renderStorylines() {
  const container = document.getElementById('storylines-list');
  if (!AdminState.advancedData.storylines.length) { container.innerHTML = '<div class="no-results">暂无剧情线，点击上方按钮添加</div>'; return; }
  const scoreLabel = getScoreLabel();
  container.innerHTML = AdminState.advancedData.storylines.map(s => `<div class="item-card ${s.is_active?'':'inactive'}">
    <div class="item-header"><span class="item-title">${escHtml(s.name)}</span><div class="item-badges">
      ${s.is_default?'<span class="item-badge active">默认</span>':''}<span class="item-badge ${s.is_active?'active':''}">${s.is_active?'启用':'禁用'}</span></div></div>
    <div class="item-content">${escHtml(s.description||'无描述')}</div>
    <div class="item-footer"><span class="item-meta">解锁${scoreLabel}: ${s.unlock_score} | 排序: ${s.sort_order}</span>
      <div class="item-actions"><button class="item-btn edit" data-action="edit-storyline" data-id="${escHtml(String(s.id))}">编辑</button></div></div></div>`).join('');
}
function updateStorylineOptions() {
  const options = AdminState.advancedData.storylines.filter(s=>s.is_active).map(s=>`<option value="${s.id}">${escHtml(s.name)}</option>`).join('');
  ['greeting-storyline','postrule-storyline','event-storyline-id'].forEach(selId => {
    const sel = document.getElementById(selId); if (!sel) return;
    const current = sel.value;
    const defaultLabel = selId==='event-storyline-id'?'不解锁剧情线':(selId==='postrule-storyline'?'通用规则':'默认');
    sel.innerHTML = `<option value="">${defaultLabel}</option>` + options; if (current) sel.value = current;
  });
}
function openStorylineModal() {
  document.getElementById('storyline-id').value=''; document.getElementById('storyline-name').value='';
  document.getElementById('storyline-description').value=''; document.getElementById('storyline-unlock-score').value=0;
  document.getElementById('storyline-sort').value=0; document.getElementById('storyline-is-default').checked=false;
  document.getElementById('storyline-is-active').checked=true;
  document.getElementById('storyline-modal-title').textContent='新增剧情线';
  document.getElementById('storyline-delete-btn').style.display='none';
  document.getElementById('storyline-modal').style.display='flex';
}
function editStoryline(id) {
  const s = AdminState.advancedData.storylines.find(x=>sameId(x.id,id)); if (!s) return;
  document.getElementById('storyline-id').value=s.id; document.getElementById('storyline-name').value=s.name;
  document.getElementById('storyline-description').value=s.description||''; document.getElementById('storyline-unlock-score').value=s.unlock_score;
  document.getElementById('storyline-sort').value=s.sort_order; document.getElementById('storyline-is-default').checked=s.is_default;
  document.getElementById('storyline-is-active').checked=s.is_active;
  document.getElementById('storyline-modal-title').textContent='编辑剧情线';
  document.getElementById('storyline-delete-btn').style.display='';
  document.getElementById('storyline-modal').style.display='flex';
}
function closeStorylineModal() { closeModal('storyline-modal'); }
async function saveStoryline() {
  const id = document.getElementById('storyline-id').value;
  await crudSave('/storylines', { name: document.getElementById('storyline-name').value, description: document.getElementById('storyline-description').value, unlock_score: parseInt(document.getElementById('storyline-unlock-score').value)||0, sort_order: parseInt(document.getElementById('storyline-sort').value)||0, is_default: document.getElementById('storyline-is-default').checked?1:0, is_active: document.getElementById('storyline-is-active').checked?1:0 }, 'storyline-modal', id);
}
async function deleteStoryline() {
  const id = document.getElementById('storyline-id').value; if (!id) return;
  let confirmMsg = '确定要删除这个剧情线吗？';
  try {
    const impact = await AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}/storylines/${id}/delete-impact`);
    const summary = impact.summary || {};
    confirmMsg = `确定要删除剧情线「${impact.storyline?.name||id}」吗？\n\n关联开场白：${summary.greeting_count||0} 条\n关联后置规则：${summary.post_rule_count||0} 条\n解锁该线的事件：${summary.unlock_event_count||0} 条\n\n删除后不会自动修复。`;
  } catch(e) { confirmMsg = '确定要删除这个剧情线吗？关联内容可能会受到影响。'; }
  await crudDelete('/storylines', id, 'storyline-modal', confirmMsg);
}

// ============================================================
// 记忆分类管理
// ============================================================
function renderCategories() {
  const container = document.getElementById('categories-list');
  if (!AdminState.advancedData.categories.length) { container.innerHTML = '<div class="no-results">暂无记忆分类，点击上方按钮添加</div>'; return; }
  container.innerHTML = AdminState.advancedData.categories.map(c => `<div class="item-card">
    <div class="item-header"><span class="item-title" style="color:${escHtml(c.color)}">● ${escHtml(c.name)}</span><div class="item-badges"><span class="item-badge">排序 ${c.sort_order}</span></div></div>
    <div class="item-content">${escHtml(c.description||'无描述')}</div>
    <div class="item-footer"><span class="item-meta">创建于 ${formatDate(c.created_at)}</span>
      <div class="item-actions"><button class="item-btn edit" data-action="edit-category" data-id="${escHtml(String(c.id))}">编辑</button></div></div></div>`).join('');
}
function openCategoryModal() {
  document.getElementById('category-id').value=''; document.getElementById('category-name').value='';
  document.getElementById('category-description').value=''; document.getElementById('category-color').value='#a855f7';
  document.getElementById('category-sort-order').value=0;
  document.getElementById('category-modal-title').textContent='新增记忆分类';
  document.getElementById('category-delete-btn').style.display='none';
  document.getElementById('category-modal').style.display='flex';
}
function editCategory(id) {
  const c = AdminState.advancedData.categories.find(x=>sameId(x.id,id)); if (!c) return;
  document.getElementById('category-id').value=c.id; document.getElementById('category-name').value=c.name;
  document.getElementById('category-description').value=c.description||''; document.getElementById('category-color').value=c.color||'#a855f7';
  document.getElementById('category-sort-order').value=c.sort_order;
  document.getElementById('category-modal-title').textContent='编辑记忆分类';
  document.getElementById('category-delete-btn').style.display='';
  document.getElementById('category-modal').style.display='flex';
}
function closeCategoryModal() { closeModal('category-modal'); }
async function saveCategory() {
  const id = document.getElementById('category-id').value;
  const data = { name: document.getElementById('category-name').value, description: document.getElementById('category-description').value, color: document.getElementById('category-color').value, sort_order: parseInt(document.getElementById('category-sort-order').value)||0 };
  if (!data.name.trim()) { toast('请输入分类名称'); return; }
  await crudSave('/memory-categories', data, 'category-modal', id);
}
async function deleteCategory() {
  const id = document.getElementById('category-id').value; if (!id) return;
  let confirmMsg = '确定删除此分类？';
  try {
    const impact = await AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}/memory-categories/${id}/delete-impact`);
    confirmMsg = `确定要删除分类「${impact.category?.name||id}」吗？\n\n当前有 ${impact.summary?.memory_count||0} 条记忆正在使用它。`;
  } catch(e) { confirmMsg = '确定删除此分类？如果还有记忆引用它，删除会失败。'; }
  await crudDelete('/memory-categories', id, 'category-modal', confirmMsg);
}

// ============================================================
// 后置规则管理
// ============================================================
function renderPostRules() {
  const container = document.getElementById('postrules-list');
  if (!AdminState.advancedData.postRules.length) { container.innerHTML = '<div class="no-results">暂无后置规则，点击上方按钮添加</div>'; return; }
  container.innerHTML = AdminState.advancedData.postRules.map(r => `<div class="item-card ${r.is_active?'':'inactive'}">
    <div class="item-header"><span class="item-title">${escHtml(r.name)}</span><div class="item-badges">
      <span class="item-badge ${r.is_active?'active':''}">${r.is_active?'启用':'禁用'}</span>
      <span class="item-badge">优先级 ${r.priority}</span>
      ${r.story_phase?`<span class="item-badge">${getPhaseLabel(r.story_phase)}</span>`:''}</div></div>
    <div class="item-content">${escHtml(r.content.substring(0,120))}${r.content.length>120?'...':''}</div>
    <div class="item-footer"><span class="item-meta">${r.storyline_id?'绑定剧情线':'通用规则'}</span>
      <div class="item-actions"><button class="item-btn edit" data-action="edit-postrule" data-id="${escHtml(String(r.id))}">编辑</button></div></div></div>`).join('');
}
function openPostRuleModal() {
  document.getElementById('postrule-id').value=''; document.getElementById('postrule-name').value='';
  document.getElementById('postrule-content').value=''; document.getElementById('postrule-storyline').value='';
  updatePhaseSelect('postrule-phase', '');
  document.getElementById('postrule-priority').value=100;
  document.getElementById('postrule-is-active').checked=true;
  document.getElementById('postrule-modal-title').textContent='新增后置规则';
  document.getElementById('postrule-delete-btn').style.display='none';
  document.getElementById('postrule-modal').style.display='flex';
}
function editPostRule(id) {
  const r = AdminState.advancedData.postRules.find(x=>sameId(x.id,id)); if (!r) return;
  document.getElementById('postrule-id').value=r.id; document.getElementById('postrule-name').value=r.name;
  document.getElementById('postrule-content').value=r.content; document.getElementById('postrule-storyline').value=r.storyline_id||'';
  updatePhaseSelect('postrule-phase', r.story_phase||'');
  document.getElementById('postrule-priority').value=r.priority;
  document.getElementById('postrule-is-active').checked=r.is_active;
  document.getElementById('postrule-modal-title').textContent='编辑后置规则';
  document.getElementById('postrule-delete-btn').style.display='';
  document.getElementById('postrule-modal').style.display='flex';
}
function closePostRuleModal() { closeModal('postrule-modal'); }
async function savePostRule() {
  const id = document.getElementById('postrule-id').value;
  const rawStorylineId = document.getElementById('postrule-storyline').value;
  const err = validateStoryline(rawStorylineId); if (err) { toast(err); return; }
  const data = { name: document.getElementById('postrule-name').value, content: document.getElementById('postrule-content').value, storyline_id: cleanStorylineId(rawStorylineId), story_phase: document.getElementById('postrule-phase').value||null, priority: parseInt(document.getElementById('postrule-priority').value)||100, is_active: document.getElementById('postrule-is-active').checked?1:0 };
  if (!data.name.trim()) { toast('请输入规则名称'); return; }
  if (!data.content.trim()) { toast('请输入规则内容'); return; }
  await crudSave('/post-rules', data, 'postrule-modal', id);
}
async function deletePostRule() { await crudDelete('/post-rules', document.getElementById('postrule-id').value, 'postrule-modal', '确定删除此后置规则？'); }

// ============================================================
// 剧情事件管理
// ============================================================
function renderEventSelectors(selectedMemoryIds=[], selectedGreetingIds=[], selectedStorylineId='') {
  const memorySelector = document.getElementById('event-memory-selector');
  const greetingSelector = document.getElementById('event-greeting-selector');
  const storylineSelect = document.getElementById('event-storyline-id');
  const selectedMemSet = new Set((selectedMemoryIds||[]).map(String));
  const selectedGreetingSet = new Set((selectedGreetingIds||[]).map(String));
  const memories = (AdminState.advancedData.memories||[]).filter(x=>x.is_active);
  memorySelector.innerHTML = memories.length ? memories.map(m=>`<label class="selector-option"><input type="checkbox" value="${m.id}" ${selectedMemSet.has(String(m.id))?'checked':''} /><div><div class="title">${escHtml(m.keywords)}</div><div class="meta">${escHtml((m.comment||m.content||'').slice(0,60))}</div></div></label>`).join('') : '<div class="selector-empty">暂无可选记忆条目</div>';
  const greetings = (AdminState.advancedData.greetings||[]).filter(x=>x.is_active);
  greetingSelector.innerHTML = greetings.length ? greetings.map(g=>`<label class="selector-option"><input type="checkbox" value="${g.id}" ${selectedGreetingSet.has(String(g.id))?'checked':''} /><div><div class="title">${escHtml(getPhaseLabel(g.story_phase))} / ${escHtml(g.mood||'neutral')}</div><div class="meta">${escHtml((g.content||'').slice(0,60))}</div></div></label>`).join('') : '<div class="selector-empty">暂无可选开场白</div>';
  const options = (AdminState.advancedData.storylines||[]).filter(s=>s.is_active).map(s=>`<option value="${s.id}">${escHtml(s.name)}</option>`).join('');
  storylineSelect.innerHTML = '<option value="">不解锁剧情线</option>' + options;
  storylineSelect.value = selectedStorylineId!=null&&selectedStorylineId!==''?String(selectedStorylineId):'';
}
function renderEvents() {
  const container = document.getElementById('events-list');
  if (!AdminState.advancedData.events.length) { container.innerHTML = '<div class="no-results">暂无剧情事件，点击上方按钮添加</div>'; return; }
  const scoreLabel = getScoreLabel();
  container.innerHTML = AdminState.advancedData.events.map(e => {
    const memoryNames = splitCsvIds(e.unlocked_memory_ids).map(getMemoryNameById);
    const greetingNames = splitCsvIds(e.unlocked_greeting_ids).map(getGreetingNameById);
    const storylineName = e.unlocked_storyline_id ? getStorylineNameById(e.unlocked_storyline_id) : '';
    const unlocks = [...memoryNames.map(n=>`<span class="item-badge">🧠 ${escHtml(n)}</span>`),...greetingNames.map(n=>`<span class="item-badge">👋 ${escHtml(n)}</span>`),...(storylineName?[`<span class="item-badge">📖 ${escHtml(storylineName)}</span>`]:[])].join('');
    return `<div class="item-card ${e.is_active?'':'inactive'}">
      <div class="item-header"><span class="item-title">${escHtml(e.title)}</span><div class="item-badges">
        <span class="item-badge ${e.is_active?'active':''}">${e.is_active?'启用':'禁用'}</span>
        <span class="item-badge">${scoreLabel} >= ${e.trigger_score}</span></div></div>
      <div class="item-content">${escHtml(e.description||'无描述')}</div>
      ${unlocks?`<div class="item-unlocks">${unlocks}</div>`:''}
      <div class="item-footer"><span class="item-meta">${unlocks?'事件触发后将解锁以上内容':'没有配置解锁内容'}</span>
        <div class="item-actions"><button class="item-btn edit" data-action="edit-event" data-id="${escHtml(String(e.id))}">编辑</button></div></div></div>`;
  }).join('');
}
function openEventModal() {
  document.getElementById('event-id').value=''; document.getElementById('event-title').value='';
  document.getElementById('event-description').value=''; document.getElementById('event-trigger-score').value=0;
  renderEventSelectors([],[],''); document.getElementById('event-content').value='';
  document.getElementById('event-sort-order').value=0; document.getElementById('event-is-active').checked=true;
  document.getElementById('event-modal-title').textContent='新增剧情事件';
  document.getElementById('event-delete-btn').style.display='none';
  document.getElementById('event-modal').style.display='flex';
}
function editEvent(id) {
  const e = AdminState.advancedData.events.find(x=>sameId(x.id,id)); if (!e) return;
  document.getElementById('event-id').value=e.id; document.getElementById('event-title').value=e.title;
  document.getElementById('event-description').value=e.description||''; document.getElementById('event-trigger-score').value=e.trigger_score;
  renderEventSelectors(splitCsvIds(e.unlocked_memory_ids),splitCsvIds(e.unlocked_greeting_ids),e.unlocked_storyline_id||'');
  document.getElementById('event-content').value=e.event_content||''; document.getElementById('event-sort-order').value=e.sort_order;
  document.getElementById('event-is-active').checked=e.is_active;
  document.getElementById('event-modal-title').textContent='编辑剧情事件';
  document.getElementById('event-delete-btn').style.display='';
  document.getElementById('event-modal').style.display='flex';
}
function closeEventModal() { closeModal('event-modal'); }
async function saveEvent() {
  const id = document.getElementById('event-id').value;
  const selectedMemoryIds = getCheckedValues('event-memory-selector');
  const selectedGreetingIds = getCheckedValues('event-greeting-selector');
  const rawStorylineId = String(document.getElementById('event-storyline-id').value||'').trim();
  const err = validateStoryline(rawStorylineId); if (err) { toast(err); return; }
  const data = { title: document.getElementById('event-title').value, description: document.getElementById('event-description').value, trigger_score: parseInt(document.getElementById('event-trigger-score').value)||0, unlocked_memory_ids: selectedMemoryIds.join(','), unlocked_greeting_ids: selectedGreetingIds.join(','), unlocked_storyline_id: cleanStorylineId(rawStorylineId), event_content: document.getElementById('event-content').value, sort_order: parseInt(document.getElementById('event-sort-order').value)||0, is_active: document.getElementById('event-is-active').checked?1:0 };
  if (!data.title.trim()) { toast('请输入事件标题'); return; }
  const hasUnlocks = selectedMemoryIds.length || selectedGreetingIds.length || data.unlocked_storyline_id;
  if (!hasUnlocks) { const goOn = await showConfirm('这个事件没有配置解锁内容。仍然保存？','提示'); if (!goOn) return; }
  if (!String(data.event_content||'').trim()) { toast('⚠️ 事件内容（event_content）是 AI 的行动指导，必须填写！\n\n示例：【剧情推进】用户发现了一把生锈的钥匙。接下来应该：引导用户前往地下室探索...'); return; }
  if (AdminState.currentCharData && !AdminState.currentCharData.affection_enabled) { const scoreLabel = getScoreLabel(); const goOn = await showConfirm(`当前角色隐藏了${scoreLabel}状态栏，用户将看不到${scoreLabel}进度。仍然继续？`,'提示'); if (!goOn) return; }
  await crudSave('/story-events', data, 'event-modal', id);
}
async function deleteEvent() { await crudDelete('/story-events', document.getElementById('event-id').value, 'event-modal', '确定删除此剧情事件？'); }

// ============================================================
// 关键词测试
// ============================================================
async function testKeywords() {
  const text = document.getElementById('test-input').value.trim();
  if (!text) { toast('请输入测试文本'); return; }
  const container = document.getElementById('test-results');
  container.innerHTML = '<div class="no-results">测试中...</div>';
  try {
    const results = await AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}/test-keywords`, { method:'POST', body:JSON.stringify({text}) });
    if (!results.length) { container.innerHTML = '<div class="no-results">没有匹配的记忆条目</div>'; return; }
    container.innerHTML = results.map(r => `<div class="test-result-item matched">
      <div class="test-result-header"><span class="test-result-title">${escHtml(r.keywords)}</span><span class="test-result-match">✓ 匹配</span></div>
      <div class="test-result-content">${escHtml(r.content.substring(0,200))}${r.content.length>200?'...':''}</div>
      <div class="test-result-keywords">匹配的关键词: <span>${escHtml(r.matched_keywords.join(', '))}</span></div></div>`).join('');
  } catch(e) { container.innerHTML = `<div class="no-results" style="color:var(--danger-light)">测试失败：${escHtml(e.message)}</div>`; }
}
