function renderCharListSidebar() {
  const container = document.getElementById('char-list');
  const q = (document.getElementById('char-filter-search')?.value || '').trim().toLowerCase();
  const vis = document.getElementById('char-filter-visible')?.value || 'all';
  const typ = document.getElementById('char-filter-type')?.value || 'all';
  const plan = document.getElementById('char-filter-plan')?.value || 'all';
  let chars = AdminState.allCharsCache.slice();
  if (vis === 'visible') chars = chars.filter(c => c.is_visible);
  if (vis === 'hidden') chars = chars.filter(c => !c.is_visible);
  if (typ !== 'all') chars = chars.filter(c => (c.card_type || 'intimate') === typ);
  if (plan !== 'all') chars = chars.filter(c => (c.required_plan || 'guest') === plan);
  if (q) {
    chars = chars.filter(c =>
      (c.name || '').toLowerCase().includes(q) ||
      (c.id || '').toLowerCase().includes(q) ||
      (c.abbr || '').toLowerCase().includes(q)
    );
  }
  if (!chars.length) {
    container.innerHTML = '<div class="empty-state"><div>无匹配角色</div></div>';
    const countEl = document.getElementById('char-count');
    if (countEl) countEl.textContent = '0';
    return;
  }
  const countEl = document.getElementById('char-count');
  if (countEl) countEl.textContent = chars.length;
  const typeMap = { intimate: '💞对话陪伴', scenario: '🎭剧情沙盒' };
  container.innerHTML = chars.map(c => {
    const typeBadge = typeMap[c.card_type] || c.card_type;
    const typeCls = `badge badge-${c.card_type || 'intimate'}`;
    const planBadge = c.required_plan && c.required_plan !== 'guest'
      ? `<span class="badge badge-${c.required_plan}">${formatPlanLabel(c.required_plan)}</span>`
      : '';
    const visBadge = c.is_visible
      ? '<span class="badge badge-visible">可见</span>'
      : '<span class="badge badge-hidden">隐藏</span>';
    return `<div class="char-item ${c.id === AdminState.currentCharId ? 'active' : ''}" data-action="select-char" data-char-id="${escHtml(String(c.id || ''))}" tabindex="0">
      <div class="char-name">${escHtml(c.name)}</div>
      <div class="char-meta">
        <span class="${typeCls}">${typeBadge}</span>
        ${planBadge}
        ${visBadge}
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
      const countEl = document.getElementById('char-count');
      if (countEl) countEl.textContent = '0';
      return;
    }
    renderCharListSidebar();
  } catch (e) {
    container.innerHTML = `<div class="empty-state" style="color:var(--danger-light)">加载失败：${escHtml(e.message)}</div>`;
  }
}

async function selectChar(charId) {
  AdminState.currentCharId = charId;
  AdminState.currentPromptPreview = null;
  document.querySelectorAll('.char-item').forEach(el => {
    el.classList.toggle('active', el.dataset.charId === String(charId));
  });
  document.getElementById('char-tabs').style.display = 'flex';
  const fab = document.getElementById('fab-save');
  const fabLabel = document.getElementById('fab-label');
  fab.style.display = 'flex';
  fabLabel.textContent = '保存';
  switchCharTab('overview');
  const overviewPanel = document.getElementById('tab-overview');
  overviewPanel.innerHTML = '<div class="empty-state"><div class="icon">⏳</div><div>加载中...</div></div>';
  try {
    const raw = await AdminAPI.apiFetch(`${AdminAPI.API}/character/${charId}`);
    if (AdminState.currentCharId !== charId) return;
    const normalized = normalizeCharacterDetail(raw);
    AdminState.currentCharData = normalized;
    AdminState.isDirty = false;
    renderEditPanel(normalized);
    loadCharacterSummary();
  } catch (e) {
    if (AdminState.currentCharId !== charId) return;
    overviewPanel.innerHTML = `<div class="empty-state" style="color:var(--danger-light)">加载失败：${escHtml(e.message)}</div>`;
  }
}

function clearCurrentCharacterSelection() {
  AdminState.currentCharId = null;
  AdminState.currentCharData = null;
  AdminState.currentCharSummary = null;
  AdminState.currentPromptPreview = null;
  document.querySelectorAll('.char-item').forEach(el => el.classList.remove('active'));
  document.getElementById('char-tabs').style.display = 'none';
  CHAR_TABS.forEach(t => {
    const el = document.getElementById(`tab-${t}`);
    if (el) el.style.display = 'none';
  });
  document.getElementById('tab-overview').innerHTML = '<div class="empty-state"><div class="icon">👈</div><div>从左侧选择一个角色开始</div></div>';
  document.getElementById('tab-overview').style.display = '';
  document.getElementById('prompt-preview-content').innerHTML = '<div class="preview-box muted">请先从左侧选择角色。</div>';
  renderCharacterOverview(null);
  const fab = document.getElementById('fab-save');
  if (fab) fab.style.display = 'none';
}
