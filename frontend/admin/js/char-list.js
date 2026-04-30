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
    return `<div class="char-item ${c.id === AdminState.currentCharId ? 'active' : ''}" data-action="select-char" data-char-id="${escHtml(String(c.id || ''))}">
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

async function selectChar(charId) {
  AdminState.currentCharId = charId;
  document.querySelectorAll('.char-item').forEach(el => {
    el.classList.toggle('active', el.dataset.charId === String(charId));
  });
  switchTab('edit');

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
