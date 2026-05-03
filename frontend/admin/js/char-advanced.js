/**
 * char-advanced.js - 高级配置标签页 + 7 个子标签的所有逻辑
 *
 * 包含：子标签切换、加载数据、记忆条目/开场白/剧情线/记忆分类/后置规则/剧情事件的 CRUD，
 * 以及关键词测试和剧情线选项同步。
 * 依赖：utils.js, api.js, state.js, main.js（ADVANCED_GUIDE_META）
 */

// ============================================================
// 通用 CRUD 辅助函数
// ============================================================

/** 关闭弹窗 */
function closeModal(modalId) {
  document.getElementById(modalId).style.display = 'none';
}

/** 清洗 storyline_id：空值返回 null */
function cleanStorylineId(raw) {
  if (!raw) return null;
  const n = raw.trim();
  return n || null;
}

/** 校验剧情线是否存在且启用，返回错误信息或 null */
function validateStoryline(rawStorylineId, inactiveMsg = '当前选择的剧情线已禁用，请先启用它或改为默认') {
  if (!rawStorylineId) return null;
  const storyline = getStorylineById(rawStorylineId);
  if (!storyline) return '当前选择的剧情线不存在，请重新选择';
  if (!storyline.is_active) return inactiveMsg;
  return null;
}

/** 通用 CRUD 保存（PUT 或 POST） */
async function crudSave(endpoint, data, modalId, idValue) {
  const url = idValue
    ? `${AdminAPI.API}/character/${AdminState.currentCharId}${endpoint}/${idValue}`
    : `${AdminAPI.API}/character/${AdminState.currentCharId}${endpoint}`;
  try {
    await AdminAPI.apiFetch(url, { method: idValue ? 'PUT' : 'POST', body: JSON.stringify(data) });
    closeModal(modalId);
    toast('保存成功');
    loadAdvancedData();
  } catch (e) {
    toast('保存失败：' + e.message);
  }
}

/** 通用 CRUD 删除 */
async function crudDelete(endpoint, idValue, modalId, confirmMsg = null) {
  if (!idValue) return;
  if (!confirm(confirmMsg || '确定删除？')) return;
  try {
    await AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}${endpoint}/${idValue}`, { method: 'DELETE' });
    closeModal(modalId);
    toast('删除成功');
    loadAdvancedData();
  } catch (e) {
    toast('删除失败：' + e.message);
  }
}

// ============================================================
// 子标签页切换
// ============================================================
function switchAdvancedTab(tab) {
  AdminState.currentAdvancedTab = tab;
  const tabs = ['memories', 'categories', 'greetings', 'storylines', 'postrules', 'events', 'test'];
  document.querySelectorAll('.sub-tab-btn').forEach((b, i) => {
    b.classList.toggle('active', tabs[i] === tab);
  });
  document.getElementById('advanced-memories').style.display = tab === 'memories' ? '' : 'none';
  document.getElementById('advanced-categories').style.display = tab === 'categories' ? '' : 'none';
  document.getElementById('advanced-greetings').style.display = tab === 'greetings' ? '' : 'none';
  document.getElementById('advanced-storylines').style.display = tab === 'storylines' ? '' : 'none';
  document.getElementById('advanced-postrules').style.display = tab === 'postrules' ? '' : 'none';
  document.getElementById('advanced-events').style.display = tab === 'events' ? '' : 'none';
  document.getElementById('advanced-test').style.display = tab === 'test' ? '' : 'none';
  renderAdvancedGuide(tab);
}

// ============================================================
// 加载高级配置数据
// ============================================================
async function loadAdvancedData() {
  if (!AdminState.currentCharId) return;

  document.getElementById('advanced-empty').style.display = 'none';
  document.getElementById('advanced-content').style.display = '';
  renderAdvancedGuide(AdminState.currentAdvancedTab);

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
    renderMemories();
    renderCategories();
    renderGreetings();
    renderStorylines();
    renderPostRules();
    renderEvents();
    updateStorylineOptions();
  } catch (e) {
    toast('加载高级配置失败：' + e.message);
  }
}

function renderAdvancedGuide(tab = AdminState.currentAdvancedTab) {
  const card = document.getElementById('advanced-guide-card');
  if (!card) return;
  const meta = ADVANCED_GUIDE_META[tab] || ADVANCED_GUIDE_META.memories;
  card.innerHTML = `
    <div class="guide-title">${meta.title}</div>
    <div class="guide-desc">${meta.desc}</div>
    <ul class="guide-list">
      ${(meta.bullets || []).map(item => `<li>${escHtml(item)}</li>`).join('')}
    </ul>
    <div class="guide-note">不熟悉配置时，建议先做：角色基础信息 → 开场白 → 记忆条目 → Prompt 预览，再考虑剧情线和事件。</div>
  `;
}

// ============================================================
// 辅助查询函数
// ============================================================
function memoryCategoryName(categoryId) {
  if (categoryId == null) return '';
  const c = (AdminState.advancedData.categories || []).find(x => x.id === categoryId);
  return c ? c.name : ('#' + categoryId);
}

function getMemoryNameById(id) {
  const item = (AdminState.advancedData.memories || []).find(x => String(x.id) === String(id));
  if (!item) return `记忆#${id}`;
  return item.keywords || item.comment || `记忆#${id}`;
}

function getGreetingNameById(id) {
  const item = (AdminState.advancedData.greetings || []).find(x => String(x.id) === String(id));
  if (!item) return `开场白#${id}`;
  return `${getPhaseLabel(item.story_phase)} / ${item.mood || 'neutral'}`;
}

function getStorylineNameById(id) {
  const item = (AdminState.advancedData.storylines || []).find(x => String(x.id) === String(id));
  if (!item) return `剧情线#${id}`;
  return item.name || `剧情线#${id}`;
}

function getStorylineById(id) {
  return (AdminState.advancedData.storylines || []).find(x => String(x.id) === String(id)) || null;
}

// ============================================================
// 记忆条目管理
// ============================================================
function updateMemoryCategoryOptions(selectedId) {
  const sel = document.getElementById('memory-category');
  const cats = AdminState.advancedData.categories || [];
  sel.innerHTML = '<option value="">不分类</option>' + cats.map(c =>
    `<option value="${c.id}">${escHtml(c.name)}</option>`).join('');
  if (selectedId != null && selectedId !== '') {
    sel.value = String(selectedId);
  } else {
    sel.value = '';
  }
}

function renderMemories() {
  const container = document.getElementById('memories-list');
  if (!AdminState.advancedData.memories.length) {
    container.innerHTML = '<div class="no-results">暂无记忆条目，点击上方按钮添加</div>';
    return;
  }

  container.innerHTML = AdminState.advancedData.memories.map(m => {
    const catLabel = memoryCategoryName(m.category_id);
    const catBadge = catLabel
      ? `<span class="item-badge" style="border:1px solid #5b21b6;color:#c084fc;">${escHtml(catLabel)}</span>`
      : '';
    return `
    <div class="item-card ${m.is_active ? '' : 'inactive'}">
      <div class="item-header">
        <span class="item-title">${escHtml(m.keywords)}</span>
        <div class="item-badges">
          ${catBadge}
          <span class="item-badge ${m.is_active ? 'active' : ''}">${m.is_active ? '启用' : '禁用'}</span>
          <span class="item-badge">${m.position === 'before' ? '前置' : '后置'}</span>
          <span class="item-badge">优先级 ${m.priority}</span>
        </div>
      </div>
      <div class="item-content">${escHtml(m.content.substring(0, 120))}${m.content.length > 120 ? '...' : ''}</div>
      <div class="item-footer">
        <span class="item-meta">${m.comment || '无备注'}</span>
        <div class="item-actions">
          <button class="item-btn edit" data-action="edit-memory" data-id="${escHtml(String(m.id))}">编辑</button>
        </div>
      </div>
    </div>
  `;
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
  updateMemoryCategoryOptions(null);
  document.getElementById('memory-modal-title').textContent = '新增记忆条目';
  document.getElementById('memory-delete-btn').style.display = 'none';
  document.getElementById('memory-modal').style.display = 'flex';
}

function editMemory(id) {
  const m = AdminState.advancedData.memories.find(x => x.id === id);
  if (!m) return;

  document.getElementById('memory-id').value = m.id;
  document.getElementById('memory-keywords').value = m.keywords;
  document.getElementById('memory-trigger-logic').value = m.trigger_logic || 'any';
  document.getElementById('memory-content').value = m.content;
  document.getElementById('memory-position').value = m.position;
  document.getElementById('memory-priority').value = m.priority;
  document.getElementById('memory-comment').value = m.comment || '';
  document.getElementById('memory-is-active').checked = m.is_active;
  updateMemoryCategoryOptions(m.category_id);
  document.getElementById('memory-modal-title').textContent = '编辑记忆条目';
  document.getElementById('memory-delete-btn').style.display = '';
  document.getElementById('memory-modal').style.display = 'flex';
}

function closeMemoryModal() { closeModal('memory-modal'); }

async function saveMemory() {
  const id = document.getElementById('memory-id').value;
  await crudSave('/memories', {
    keywords: document.getElementById('memory-keywords').value,
    trigger_logic: document.getElementById('memory-trigger-logic').value,
    content: document.getElementById('memory-content').value,
    position: document.getElementById('memory-position').value,
    priority: parseInt(document.getElementById('memory-priority').value) || 100,
    comment: document.getElementById('memory-comment').value,
    is_active: document.getElementById('memory-is-active').checked ? 1 : 0,
    category_id: cleanStorylineId(document.getElementById('memory-category').value),
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
  if (AdminState.currentGreetingFilter !== 'all') {
    greetings = greetings.filter(g => g.story_phase === AdminState.currentGreetingFilter);
  }

  if (!greetings.length) {
    container.innerHTML = '<div class="no-results">该阶段暂无开场白</div>';
    return;
  }

  const phaseNames = { stranger: '陌生人', acquaintance: '熟人', friend: '朋友', lover: '恋人' };
  const moodEmojis = { neutral: '😐', happy: '😊', sad: '😢', angry: '😠', flirty: '😉' };

  container.innerHTML = greetings.map(g => `
    <div class="item-card ${g.is_active ? '' : 'inactive'}">
      <div class="item-header">
        <div class="item-badges">
          <span class="item-badge phase-${g.story_phase}">${phaseNames[g.story_phase] || g.story_phase}</span>
          <span class="item-badge">${moodEmojis[g.mood] || ''} ${g.mood}</span>
          <span class="item-badge ${g.is_active ? 'active' : ''}">${g.is_active ? '启用' : '禁用'}</span>
        </div>
        <span class="item-meta">优先级 ${g.priority}</span>
      </div>
      <div class="item-content">${escHtml(g.content.substring(0, 150))}${g.content.length > 150 ? '...' : ''}</div>
      <div class="item-footer">
        <span class="item-meta">使用 ${g.use_count || 0} 次</span>
        <div class="item-actions">
          <button class="item-btn edit" data-action="edit-greeting" data-id="${escHtml(String(g.id))}">编辑</button>
        </div>
      </div>
    </div>
  `).join('');
}

function filterGreetings(phase) {
  AdminState.currentGreetingFilter = phase;
  document.querySelectorAll('.phase-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.phase === phase);
  });
  renderGreetings();
}

function openGreetingModal() {
  document.getElementById('greeting-id').value = '';
  document.getElementById('greeting-content').value = '';
  document.getElementById('greeting-phase').value = 'stranger';
  document.getElementById('greeting-mood').value = 'neutral';
  document.getElementById('greeting-priority').value = 100;
  document.getElementById('greeting-storyline').value = '';
  document.getElementById('greeting-is-active').checked = true;
  document.getElementById('greeting-modal-title').textContent = '新增开场白';
  document.getElementById('greeting-delete-btn').style.display = 'none';
  document.getElementById('greeting-modal').style.display = 'flex';
}

function editGreeting(id) {
  const g = AdminState.advancedData.greetings.find(x => x.id === id);
  if (!g) return;

  document.getElementById('greeting-id').value = g.id;
  document.getElementById('greeting-content').value = g.content;
  document.getElementById('greeting-phase').value = g.story_phase;
  document.getElementById('greeting-mood').value = g.mood;
  document.getElementById('greeting-priority').value = g.priority;
  document.getElementById('greeting-storyline').value = g.storyline_id || '';
  document.getElementById('greeting-is-active').checked = g.is_active;
  document.getElementById('greeting-modal-title').textContent = '编辑开场白';
  document.getElementById('greeting-delete-btn').style.display = '';
  document.getElementById('greeting-modal').style.display = 'flex';
}

function closeGreetingModal() { closeModal('greeting-modal'); }

async function saveGreeting() {
  const id = document.getElementById('greeting-id').value;
  const rawStorylineId = document.getElementById('greeting-storyline').value;
  const err = validateStoryline(rawStorylineId, '当前选择的剧情线已禁用，请先启用它或改为默认');
  if (err) { toast(err); return; }

  await crudSave('/greetings', {
    content: document.getElementById('greeting-content').value,
    story_phase: document.getElementById('greeting-phase').value,
    mood: document.getElementById('greeting-mood').value,
    priority: parseInt(document.getElementById('greeting-priority').value) || 100,
    storyline_id: cleanStorylineId(rawStorylineId),
    is_active: document.getElementById('greeting-is-active').checked ? 1 : 0,
  }, 'greeting-modal', id);
}

async function deleteGreeting() {
  await crudDelete('/greetings', document.getElementById('greeting-id').value, 'greeting-modal', '确定要删除这个开场白吗？');
}

// ============================================================
// 剧情线管理
// ============================================================
function renderStorylines() {
  const container = document.getElementById('storylines-list');
  if (!AdminState.advancedData.storylines.length) {
    container.innerHTML = '<div class="no-results">暂无剧情线，点击上方按钮添加</div>';
    return;
  }

  container.innerHTML = AdminState.advancedData.storylines.map(s => `
    <div class="item-card ${s.is_active ? '' : 'inactive'}">
      <div class="item-header">
        <span class="item-title">${escHtml(s.name)}</span>
        <div class="item-badges">
          ${s.is_default ? '<span class="item-badge active">默认</span>' : ''}
          <span class="item-badge ${s.is_active ? 'active' : ''}">${s.is_active ? '启用' : '禁用'}</span>
        </div>
      </div>
      <div class="item-content">${escHtml(s.description || '无描述')}</div>
      <div class="item-footer">
        <span class="item-meta">解锁好感度: ${s.unlock_score} | 排序: ${s.sort_order}</span>
        <div class="item-actions">
          <button class="item-btn edit" data-action="edit-storyline" data-id="${escHtml(String(s.id))}">编辑</button>
        </div>
      </div>
    </div>
  `).join('');
}

function updateStorylineOptions() {
  const options = AdminState.advancedData.storylines
    .filter(s => s.is_active)
    .map(s => `<option value="${s.id}">${escHtml(s.name)}</option>`)
    .join('');

  const greetingSelect = document.getElementById('greeting-storyline');
  if (greetingSelect) {
    const currentValue = greetingSelect.value;
    greetingSelect.innerHTML = '<option value="">默认</option>' + options;
    if (currentValue) greetingSelect.value = currentValue;
  }

  const postRuleSelect = document.getElementById('postrule-storyline');
  if (postRuleSelect) {
    const currentValue = postRuleSelect.value;
    postRuleSelect.innerHTML = '<option value="">通用规则</option>' + options;
    if (currentValue) postRuleSelect.value = currentValue;
  }

  const eventStorylineSelect = document.getElementById('event-storyline-id');
  if (eventStorylineSelect) {
    const currentValue = eventStorylineSelect.value;
    eventStorylineSelect.innerHTML = '<option value="">不解锁剧情线</option>' + options;
    if (currentValue) eventStorylineSelect.value = currentValue;
  }
}

function openStorylineModal() {
  document.getElementById('storyline-id').value = '';
  document.getElementById('storyline-name').value = '';
  document.getElementById('storyline-description').value = '';
  document.getElementById('storyline-unlock-score').value = 0;
  document.getElementById('storyline-sort').value = 0;
  document.getElementById('storyline-is-default').checked = false;
  document.getElementById('storyline-is-active').checked = true;
  document.getElementById('storyline-modal-title').textContent = '新增剧情线';
  document.getElementById('storyline-delete-btn').style.display = 'none';
  document.getElementById('storyline-modal').style.display = 'flex';
}

function editStoryline(id) {
  const s = AdminState.advancedData.storylines.find(x => x.id === id);
  if (!s) return;

  document.getElementById('storyline-id').value = s.id;
  document.getElementById('storyline-name').value = s.name;
  document.getElementById('storyline-description').value = s.description || '';
  document.getElementById('storyline-unlock-score').value = s.unlock_score;
  document.getElementById('storyline-sort').value = s.sort_order;
  document.getElementById('storyline-is-default').checked = s.is_default;
  document.getElementById('storyline-is-active').checked = s.is_active;
  document.getElementById('storyline-modal-title').textContent = '编辑剧情线';
  document.getElementById('storyline-delete-btn').style.display = '';
  document.getElementById('storyline-modal').style.display = 'flex';
}

function closeStorylineModal() { closeModal('storyline-modal'); }

async function saveStoryline() {
  const id = document.getElementById('storyline-id').value;
  await crudSave('/storylines', {
    name: document.getElementById('storyline-name').value,
    description: document.getElementById('storyline-description').value,
    unlock_score: parseInt(document.getElementById('storyline-unlock-score').value) || 0,
    sort_order: parseInt(document.getElementById('storyline-sort').value) || 0,
    is_default: document.getElementById('storyline-is-default').checked ? 1 : 0,
    is_active: document.getElementById('storyline-is-active').checked ? 1 : 0,
  }, 'storyline-modal', id);
}

async function deleteStoryline() {
  const id = document.getElementById('storyline-id').value;
  if (!id) return;

  let confirmMsg = '确定要删除这个剧情线吗？';
  try {
    const impact = await AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}/storylines/${id}/delete-impact`);
    const summary = impact.summary || {};
    const greetingList = (impact.impact?.greetings || []).slice(0, 3).map(x => `- 开场白：${x.label}`).join('\n');
    const postRuleList = (impact.impact?.post_rules || []).slice(0, 3).map(x => `- 后置规则：${x.label}`).join('\n');
    const eventList = (impact.impact?.unlock_events || []).slice(0, 3).map(x => `- 剧情事件：${x.label}`).join('\n');
    confirmMsg =
      `确定要删除剧情线「${impact.storyline?.name || id}」吗？\n\n` +
      `会受影响的内容：\n` +
      `- 关联开场白：${summary.greeting_count || 0} 条\n` +
      `- 关联后置规则：${summary.post_rule_count || 0} 条\n` +
      `- 解锁该剧情线的事件：${summary.unlock_event_count || 0} 条\n` +
      `${impact.storyline?.is_default ? '\n⚠️ 它当前还是默认剧情线。\n' : '\n'}` +
      `${greetingList ? '\n' + greetingList : ''}` +
      `${postRuleList ? '\n' + postRuleList : ''}` +
      `${eventList ? '\n' + eventList : ''}\n\n` +
      `删除后，这些配置不会自动修复，请确认。`;
  } catch (e) {
    confirmMsg = '确定要删除这个剧情线吗？关联的开场白、后置规则、剧情事件可能会受到影响。';
  }

  await crudDelete('/storylines', id, 'storyline-modal', confirmMsg);
}

// ============================================================
// 记忆分类管理
// ============================================================
function renderCategories() {
  const container = document.getElementById('categories-list');
  if (!AdminState.advancedData.categories.length) {
    container.innerHTML = '<div class="no-results">暂无记忆分类，点击上方按钮添加</div>';
    return;
  }
  container.innerHTML = AdminState.advancedData.categories.map(c => `
    <div class="item-card">
      <div class="item-header">
        <span class="item-title" style="color:${escHtml(c.color)}">● ${escHtml(c.name)}</span>
        <div class="item-badges">
          <span class="item-badge">排序 ${c.sort_order}</span>
        </div>
      </div>
      <div class="item-content">${escHtml(c.description || '无描述')}</div>
      <div class="item-footer">
        <span class="item-meta">创建于 ${formatDate(c.created_at)}</span>
        <div class="item-actions">
          <button class="item-btn edit" data-action="edit-category" data-id="${escHtml(String(c.id))}">编辑</button>
        </div>
      </div>
    </div>
  `).join('');
}

function openCategoryModal() {
  document.getElementById('category-id').value = '';
  document.getElementById('category-name').value = '';
  document.getElementById('category-description').value = '';
  document.getElementById('category-color').value = '#a855f7';
  document.getElementById('category-sort-order').value = 0;
  document.getElementById('category-modal-title').textContent = '新增记忆分类';
  document.getElementById('category-delete-btn').style.display = 'none';
  document.getElementById('category-modal').style.display = 'flex';
}

function editCategory(id) {
  const c = AdminState.advancedData.categories.find(x => x.id === id);
  if (!c) return;

  document.getElementById('category-id').value = c.id;
  document.getElementById('category-name').value = c.name;
  document.getElementById('category-description').value = c.description || '';
  document.getElementById('category-color').value = c.color || '#a855f7';
  document.getElementById('category-sort-order').value = c.sort_order;
  document.getElementById('category-modal-title').textContent = '编辑记忆分类';
  document.getElementById('category-delete-btn').style.display = '';
  document.getElementById('category-modal').style.display = 'flex';
}

function closeCategoryModal() { closeModal('category-modal'); }

async function saveCategory() {
  const id = document.getElementById('category-id').value;
  const data = {
    name: document.getElementById('category-name').value,
    description: document.getElementById('category-description').value,
    color: document.getElementById('category-color').value,
    sort_order: parseInt(document.getElementById('category-sort-order').value) || 0,
  };

  if (!data.name.trim()) { toast('请输入分类名称'); return; }
  await crudSave('/memory-categories', data, 'category-modal', id);
}

async function deleteCategory() {
  const id = document.getElementById('category-id').value;
  if (!id) return;

  let confirmMsg = '确定删除此分类？';
  try {
    const impact = await AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}/memory-categories/${id}/delete-impact`);
    const memories = impact.impact?.memories || [];
    confirmMsg =
      `确定要删除分类「${impact.category?.name || id}」吗？\n\n` +
      `当前有 ${impact.summary?.memory_count || 0} 条记忆正在使用它。\n` +
      `${memories.slice(0, 5).map(x => `- ${x.label}`).join('\n')}` +
      `\n\n建议先去修改这些记忆的分类，再删除。若继续删除，后端也会阻止未清理干净的情况。`;
  } catch (e) {
    confirmMsg = '确定删除此分类？如果还有记忆条目引用它，删除会失败。';
  }

  await crudDelete('/memory-categories', id, 'category-modal', confirmMsg);
}

// ============================================================
// 后置规则管理
// ============================================================
function renderPostRules() {
  const container = document.getElementById('postrules-list');
  if (!AdminState.advancedData.postRules.length) {
    container.innerHTML = '<div class="no-results">暂无后置规则，点击上方按钮添加</div>';
    return;
  }

    container.innerHTML = AdminState.advancedData.postRules.map(r => `
    <div class="item-card ${r.is_active ? '' : 'inactive'}">
      <div class="item-header">
        <span class="item-title">${escHtml(r.name)}</span>
        <div class="item-badges">
          <span class="item-badge ${r.is_active ? 'active' : ''}">${r.is_active ? '启用' : '禁用'}</span>
          <span class="item-badge">优先级 ${r.priority}</span>
          ${r.story_phase ? `<span class="item-badge">${getPhaseLabel(r.story_phase)}</span>` : ''}
        </div>
      </div>
      <div class="item-content">${escHtml(r.content.substring(0, 120))}${r.content.length > 120 ? '...' : ''}</div>
      <div class="item-footer">
        <span class="item-meta">${r.storyline_id ? '绑定剧情线' : '通用规则'}</span>
        <div class="item-actions">
          <button class="item-btn edit" data-action="edit-postrule" data-id="${escHtml(String(r.id))}">编辑</button>
        </div>
      </div>
    </div>
  `).join('');
}

function openPostRuleModal() {
  document.getElementById('postrule-id').value = '';
  document.getElementById('postrule-name').value = '';
  document.getElementById('postrule-content').value = '';
  document.getElementById('postrule-storyline').value = '';
  document.getElementById('postrule-phase').value = '';
  document.getElementById('postrule-priority').value = 100;
  document.getElementById('postrule-is-active').checked = true;
  document.getElementById('postrule-modal-title').textContent = '新增后置规则';
  document.getElementById('postrule-delete-btn').style.display = 'none';
  document.getElementById('postrule-modal').style.display = 'flex';
}

function editPostRule(id) {
  const r = AdminState.advancedData.postRules.find(x => x.id === id);
  if (!r) return;

  document.getElementById('postrule-id').value = r.id;
  document.getElementById('postrule-name').value = r.name;
  document.getElementById('postrule-content').value = r.content;
  document.getElementById('postrule-storyline').value = r.storyline_id || '';
  document.getElementById('postrule-phase').value = r.story_phase || '';
  document.getElementById('postrule-priority').value = r.priority;
  document.getElementById('postrule-is-active').checked = r.is_active;
  document.getElementById('postrule-modal-title').textContent = '编辑后置规则';
  document.getElementById('postrule-delete-btn').style.display = '';
  document.getElementById('postrule-modal').style.display = 'flex';
}

function closePostRuleModal() { closeModal('postrule-modal'); }

async function savePostRule() {
  const id = document.getElementById('postrule-id').value;
  const rawStorylineId = document.getElementById('postrule-storyline').value;
  const err = validateStoryline(rawStorylineId, '当前选择的剧情线已禁用，请先启用它或改为通用规则');
  if (err) { toast(err); return; }

  const data = {
    name: document.getElementById('postrule-name').value,
    content: document.getElementById('postrule-content').value,
    storyline_id: cleanStorylineId(rawStorylineId),
    story_phase: document.getElementById('postrule-phase').value || null,
    priority: parseInt(document.getElementById('postrule-priority').value) || 100,
    is_active: document.getElementById('postrule-is-active').checked ? 1 : 0,
  };

  if (!data.name.trim()) { toast('请输入规则名称'); return; }
  if (!data.content.trim()) { toast('请输入规则内容'); return; }

  await crudSave('/post-rules', data, 'postrule-modal', id);
}

async function deletePostRule() {
  await crudDelete('/post-rules', document.getElementById('postrule-id').value, 'postrule-modal', '确定删除此后置规则？');
}

// ============================================================
// 剧情事件管理
// ============================================================
function renderEventSelectors(selectedMemoryIds = [], selectedGreetingIds = [], selectedStorylineId = '') {
  const memorySelector = document.getElementById('event-memory-selector');
  const greetingSelector = document.getElementById('event-greeting-selector');
  const storylineSelect = document.getElementById('event-storyline-id');

  const selectedMemSet = new Set((selectedMemoryIds || []).map(String));
  const selectedGreetingSet = new Set((selectedGreetingIds || []).map(String));

  const memories = (AdminState.advancedData.memories || []).filter(x => x.is_active);
  memorySelector.innerHTML = memories.length ? memories.map(m => `
    <label class="selector-option">
      <input type="checkbox" value="${m.id}" ${selectedMemSet.has(String(m.id)) ? 'checked' : ''} />
      <div>
        <div class="title">${escHtml(m.keywords)}</div>
        <div class="meta">${escHtml((m.comment || m.content || '').slice(0, 60))}</div>
      </div>
    </label>
  `).join('') : '<div class="selector-empty">暂无可选记忆条目</div>';

  const greetings = (AdminState.advancedData.greetings || []).filter(x => x.is_active);
  greetingSelector.innerHTML = greetings.length ? greetings.map(g => `
    <label class="selector-option">
      <input type="checkbox" value="${g.id}" ${selectedGreetingSet.has(String(g.id)) ? 'checked' : ''} />
      <div>
        <div class="title">${escHtml(getPhaseLabel(g.story_phase))} / ${escHtml(g.mood || 'neutral')}</div>
        <div class="meta">${escHtml((g.content || '').slice(0, 60))}</div>
      </div>
    </label>
  `).join('') : '<div class="selector-empty">暂无可选开场白</div>';

  const options = (AdminState.advancedData.storylines || [])
    .filter(s => s.is_active)
    .map(s => `<option value="${s.id}">${escHtml(s.name)}</option>`)
    .join('');
  storylineSelect.innerHTML = '<option value="">不解锁剧情线</option>' + options;
  storylineSelect.value = selectedStorylineId != null && selectedStorylineId !== '' ? String(selectedStorylineId) : '';
}

function renderEvents() {
  const container = document.getElementById('events-list');
  if (!AdminState.advancedData.events.length) {
    container.innerHTML = '<div class="no-results">暂无剧情事件，点击上方按钮添加</div>';
    return;
  }
  container.innerHTML = AdminState.advancedData.events.map(e => {
    const memoryNames = splitCsvIds(e.unlocked_memory_ids).map(getMemoryNameById);
    const greetingNames = splitCsvIds(e.unlocked_greeting_ids).map(getGreetingNameById);
    const storylineName = e.unlocked_storyline_id ? getStorylineNameById(e.unlocked_storyline_id) : '';
    const unlocks = [
      ...memoryNames.map(name => `<span class="item-badge">🧠 ${escHtml(name)}</span>`),
      ...greetingNames.map(name => `<span class="item-badge">👋 ${escHtml(name)}</span>`),
      ...(storylineName ? [`<span class="item-badge">📖 ${escHtml(storylineName)}</span>`] : [])
    ].join('');

    return `
      <div class="item-card ${e.is_active ? '' : 'inactive'}">
        <div class="item-header">
          <span class="item-title">${escHtml(e.title)}</span>
          <div class="item-badges">
            <span class="item-badge ${e.is_active ? 'active' : ''}">${e.is_active ? '启用' : '禁用'}</span>
            <span class="item-badge">好感度 >= ${e.trigger_score}</span>
          </div>
        </div>
        <div class="item-content">${escHtml(e.description || '无描述')}</div>
        ${unlocks ? `<div class="item-unlocks">${unlocks}</div>` : ''}
        <div class="item-footer">
          <span class="item-meta">${unlocks ? '事件触发后将解锁以上内容' : '这个事件目前没有配置解锁内容'}</span>
          <div class="item-actions">
            <button class="item-btn edit" data-action="edit-event" data-id="${escHtml(String(e.id))}">编辑</button>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function openEventModal() {
  document.getElementById('event-id').value = '';
  document.getElementById('event-title').value = '';
  document.getElementById('event-description').value = '';
  document.getElementById('event-trigger-score').value = 0;
  renderEventSelectors([], [], '');
  document.getElementById('event-content').value = '';
  document.getElementById('event-sort-order').value = 0;
  document.getElementById('event-is-active').checked = true;
  document.getElementById('event-modal-title').textContent = '新增剧情事件';
  document.getElementById('event-delete-btn').style.display = 'none';
  document.getElementById('event-modal').style.display = 'flex';
}

function editEvent(id) {
  const e = AdminState.advancedData.events.find(x => x.id === id);
  if (!e) return;

  document.getElementById('event-id').value = e.id;
  document.getElementById('event-title').value = e.title;
  document.getElementById('event-description').value = e.description || '';
  document.getElementById('event-trigger-score').value = e.trigger_score;
  renderEventSelectors(
    splitCsvIds(e.unlocked_memory_ids),
    splitCsvIds(e.unlocked_greeting_ids),
    e.unlocked_storyline_id || ''
  );
  document.getElementById('event-content').value = e.event_content || '';
  document.getElementById('event-sort-order').value = e.sort_order;
  document.getElementById('event-is-active').checked = e.is_active;
  document.getElementById('event-modal-title').textContent = '编辑剧情事件';
  document.getElementById('event-delete-btn').style.display = '';
  document.getElementById('event-modal').style.display = 'flex';
}

function closeEventModal() { closeModal('event-modal'); }

async function saveEvent() {
  const id = document.getElementById('event-id').value;
  const selectedMemoryIds = getCheckedValues('event-memory-selector');
  const selectedGreetingIds = getCheckedValues('event-greeting-selector');
  const rawStorylineId = String(document.getElementById('event-storyline-id').value || '').trim();
  const err = validateStoryline(rawStorylineId, '当前选择的解锁剧情线已禁用，请先启用它');
  if (err) { toast(err); return; }

  const data = {
    title: document.getElementById('event-title').value,
    description: document.getElementById('event-description').value,
    trigger_score: parseInt(document.getElementById('event-trigger-score').value) || 0,
    unlocked_memory_ids: selectedMemoryIds.join(','),
    unlocked_greeting_ids: selectedGreetingIds.join(','),
    unlocked_storyline_id: cleanStorylineId(rawStorylineId),
    event_content: document.getElementById('event-content').value,
    sort_order: parseInt(document.getElementById('event-sort-order').value) || 0,
    is_active: document.getElementById('event-is-active').checked ? 1 : 0,
  };

  if (!data.title.trim()) { toast('请输入事件标题'); return; }
  const hasUnlocks = selectedMemoryIds.length || selectedGreetingIds.length || data.unlocked_storyline_id;
  if (!hasUnlocks) {
    const goOn = confirm('这个剧情事件还没有配置任何解锁内容。这样保存也可以，但后续很容易忘记补。仍然继续保存吗？');
    if (!goOn) return;
  }
  if (!String(data.event_content || '').trim()) {
    const goOn = confirm('这个剧情事件还没有填写事件触发文案。仍然继续保存吗？');
    if (!goOn) return;
  }
  if (AdminState.currentCharData && !AdminState.currentCharData.affection_enabled) {
    const goOn = confirm('当前角色尚未启用好感度系统，但你正在保存剧情事件。事件可能无法按预期触发。仍然继续吗？');
    if (!goOn) return;
  }

  await crudSave('/story-events', data, 'event-modal', id);
}

async function deleteEvent() {
  await crudDelete('/story-events', document.getElementById('event-id').value, 'event-modal', '确定删除此剧情事件？');
}

// ============================================================
// 关键词测试
// ============================================================
async function testKeywords() {
  const text = document.getElementById('test-input').value.trim();
  if (!text) {
    toast('请输入测试文本');
    return;
  }

  const container = document.getElementById('test-results');
  container.innerHTML = '<div class="no-results">测试中...</div>';

  try {
    const results = await AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}/test-keywords`, {
      method: 'POST',
      body: JSON.stringify({ text }),
    });

    if (!results.length) {
      container.innerHTML = '<div class="no-results">没有匹配的记忆条目</div>';
      return;
    }

    container.innerHTML = results.map(r => `
      <div class="test-result-item matched">
        <div class="test-result-header">
          <span class="test-result-title">${escHtml(r.keywords)}</span>
          <span class="test-result-match">✓ 匹配</span>
        </div>
        <div class="test-result-content">${escHtml(r.content.substring(0, 200))}${r.content.length > 200 ? '...' : ''}</div>
        <div class="test-result-keywords">匹配的关键词: <span>${escHtml(r.matched_keywords.join(', '))}</span></div>
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = `<div class="no-results" style="color:#f87171">测试失败：${e.message}</div>`;
  }
}
