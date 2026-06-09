/**
 * bootstrap.js - 启动绑定逻辑
 * 重构版：5个角色标签 + 3个系统标签 + 顶栏导航 + ESC关闭弹窗
 */

// ============================================================
// 标签切换
// ============================================================
const CHAR_TABS = ['overview', 'edit', 'worldinfo', 'story', 'preview'];
const SYSTEM_TABS = ['dashboard', 'membership', 'auditlog'];
const _layoutEl = () => document.querySelector('.layout');

function _syncHash(isSystem, tab) {
  // 写入 URL hash，刷新/分享不丢失标签页位置
  if (isSystem) {
    history.replaceState(null, '', `#${tab}`);
  } else if (tab && AdminState.currentCharId) {
    history.replaceState(null, '', `#char/${AdminState.currentCharId}/${tab}`);
  }
}

/** 更新面包屑导航 */
function _updateBreadcrumb(isSystem, tab) {
  const el = document.getElementById('breadcrumb');
  if (!el) return;
  if (isSystem) {
    const labels = { dashboard: '仪表盘', membership: '会员', auditlog: '日志' };
    el.innerHTML = `<span>系统</span><span class="sep">/</span><span>${labels[tab] || tab}</span>`;
  } else {
    const labels = { overview: '总览', edit: '编辑', worldinfo: '世界书', story: '剧情', preview: '预览' };
    const charName = AdminState.currentCharData?.name || AdminState.currentCharId || '…';
    el.innerHTML = `<span>角色</span><span class="sep">/</span><span>${escHtml(charName)}</span><span class="sep">/</span><span>${labels[tab] || tab}</span>`;
  }
}

async function switchCharTab(tab) {
  // 离开编辑 Tab 时检查是否有未保存修改
  if (AdminState.currentCharTab === 'edit' && tab !== 'edit' && AdminState.isDirty) {
    var confirmed = await showConfirm('当前有未保存的修改，切换标签页会丢失这些修改。确定要切换吗？', '未保存修改');
    if (!confirmed) return;
  }
  AdminState.isDirty = false;
  AdminState.currentCharTab = tab;
  AdminState.currentSystemTab = null;

  document.querySelectorAll('.char-tabs .tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });
  document.querySelectorAll('.topbar-link').forEach(btn => btn.classList.remove('active'));

  // 展开侧边栏
  const layout = _layoutEl();
  if (layout) layout.classList.remove('sidebar-collapsed');

  CHAR_TABS.forEach(t => {
    const el = document.getElementById(`tab-${t}`);
    if (el) el.style.display = t === tab ? '' : 'none';
  });
  SYSTEM_TABS.forEach(t => {
    const el = document.getElementById(`tab-${t}`);
    if (el) el.style.display = 'none';
  });

  // 隐藏“返回角色”按钮
  const backBtn = document.getElementById('back-to-chars-btn');
  if (backBtn) backBtn.classList.add('d-none');

  if (tab === 'worldinfo' && AdminState.currentCharId) loadAdvancedData();
  if (tab === 'story' && AdminState.currentCharId) loadAdvancedData();
  if (tab === 'preview' && AdminState.currentCharId) {
    await loadAdvancedData();
    loadPromptPreview();
  }
  _syncHash(false, tab);
  _updateBreadcrumb(false, tab);
}

async function switchSystemTab(tab) {
  // 离开编辑 Tab 时检查是否有未保存修改
  if (AdminState.currentCharTab === 'edit' && AdminState.isDirty) {
    var confirmed = await showConfirm('当前有未保存的修改，切换标签页会丢失这些修改。确定要切换吗？', '未保存修改');
    if (!confirmed) return;
  }
  AdminState.isDirty = false;
  AdminState.currentSystemTab = tab;

  document.querySelectorAll('.topbar-link').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });
  document.querySelectorAll('.char-tabs .tab-btn').forEach(btn => btn.classList.remove('active'));

  // 系统标签页时收起侧边栏，释放屏幕空间
  const layout = _layoutEl();
  if (layout) layout.classList.add('sidebar-collapsed');

  CHAR_TABS.forEach(t => {
    const el = document.getElementById(`tab-${t}`);
    if (el) el.style.display = 'none';
  });
  SYSTEM_TABS.forEach(t => {
    const el = document.getElementById(`tab-${t}`);
    if (el) el.style.display = t === tab ? '' : 'none';
  });

  // 显示“返回角色”按钮
  const backBtn = document.getElementById('back-to-chars-btn');
  if (backBtn) backBtn.classList.remove('d-none');

  if (tab === 'membership') loadMembershipData();
  if (tab === 'dashboard') loadDashboard();
  if (tab === 'auditlog') loadAuditLogs();
  _syncHash(true, tab);
  _updateBreadcrumb(true, tab);
}

// ============================================================
// 自定义确认弹窗
// ============================================================
function showConfirm(message, title = '确认操作') {
  return new Promise((resolve) => {
    document.getElementById('confirm-modal-title').textContent = title;
    document.getElementById('confirm-modal-message').textContent = message;
    document.getElementById('confirm-modal').style.display = 'flex';
    AdminState.confirmResolver = resolve;
  });
}

function closeConfirmModal(result = false) {
  document.getElementById('confirm-modal').style.display = 'none';
  if (AdminState.confirmResolver) {
    AdminState.confirmResolver(result);
    AdminState.confirmResolver = null;
  }
}

// ============================================================
// 事件绑定
// ============================================================
function bindAdminDelegatedEvents(handlePrimaryAction) {
  document.addEventListener('click', (event) => {
    const actionTrigger = event.target.closest('[data-action]');
    if (actionTrigger) {
      const action = actionTrigger.dataset.action;
      if (handlePrimaryAction(action, actionTrigger)) {
        event.preventDefault();
        return;
      }
    }
    const charTabTrigger = event.target.closest('.char-tabs .tab-btn[data-tab]');
    if (charTabTrigger) {
      event.preventDefault();
      switchCharTab(charTabTrigger.dataset.tab);
      return;
    }
  });
}

function bindAdminInputEvents() {
  const bind = (id, eventName, handler) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener(eventName, handler);
  };

  bind('char-filter-search', 'input', debounce(() => renderCharListSidebar(), 200));
  bind('char-filter-visible', 'change', () => renderCharListSidebar());
  bind('char-filter-type', 'change', () => renderCharListSidebar());
  bind('char-filter-plan', 'change', () => renderCharListSidebar());
  bind('user-search', 'input', debounce(() => filterUsers(), 200));
  bind('user-plan-filter', 'change', () => filterUsers());
  bind('order-search', 'input', debounce(() => filterOrders(), 400));
  bind('order-status-filter', 'change', () => filterOrders());
  bind('audit-action-filter', 'change', () => loadAuditLogs());
  bind('audit-date-from', 'change', () => { AdminState.auditPage = 1; loadAuditLogs(); });
  bind('audit-date-to', 'change', () => { AdminState.auditPage = 1; loadAuditLogs(); });

  document.addEventListener('input', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.matches('[data-update-len="true"]')) {
      updateLen(target);
    }
    if (target.matches('[data-affection-raw-json="true"]')) {
      target.dataset.affectionRawEdited = 'true';
      validateAffectionRulesEditor();
      return;
    }
    if (
      target.matches('[data-affection-key], [data-affection-custom-key], [data-affection-custom-score], [data-affection-meta]')
      || target.matches('[data-affection-sync="true"]')
    ) {
      const rawRules = document.getElementById('field-affection_rules_json');
      if (rawRules) rawRules.dataset.affectionRawEdited = 'false';
      syncAffectionRulesEditor();
    }
    if (target.matches('[data-phase-behavior-input="true"]')) {
      syncPhaseBehaviorsEditor();
    }
    if (target.matches('[data-life-profile-input="true"]')) {
      syncLifeProfileEditor();
    }
  });

  document.addEventListener('change', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.matches('[data-affection-refresh="true"]')) {
      const rawRules = document.getElementById('field-affection_rules_json');
      if (rawRules) rawRules.dataset.affectionRawEdited = 'false';
      syncAffectionRulesEditor();
      refreshAffectionEditor();
      return;
    }
    if (
      target.matches('[data-affection-key], [data-affection-custom-key], [data-affection-custom-score], [data-affection-meta]')
      || target.matches('[data-affection-sync="true"]')
    ) {
      const rawRules = document.getElementById('field-affection_rules_json');
      if (rawRules) rawRules.dataset.affectionRawEdited = 'false';
      syncAffectionRulesEditor();
    }
    if (target.matches('[data-user-check-all="true"]')) {
      toggleAllUsers(target);
      return;
    }
    if (target.matches('[data-user-select="true"]')) {
      toggleUserSelection(target.value, target);
    }
  });

  // 记忆筛选
  bind('memory-search', 'input', debounce(() => {
    AdminState.memorySearchQuery = document.getElementById('memory-search')?.value?.trim().toLowerCase() || '';
    renderMemories();
  }, 200));
  bind('memory-filter-category', 'change', () => {
    AdminState.memoryFilterCategory = document.getElementById('memory-filter-category')?.value || 'all';
    renderMemories();
  });
  bind('memory-filter-status', 'change', () => {
    AdminState.memoryFilterStatus = document.getElementById('memory-filter-status')?.value || 'all';
    renderMemories();
  });
  bind('memory-filter-mode', 'change', () => {
    AdminState.memoryFilterMode = document.getElementById('memory-filter-mode')?.value || 'all';
    renderMemories();
  });

  // 触发模式提示
  bind('memory-trigger-mode', 'change', () => {
    const mode = document.getElementById('memory-trigger-mode')?.value;
    const hint = document.getElementById('memory-mode-hint');
    if (!hint) return;
    const hints = {
      keyword: '<strong>关键词触发</strong>：只有用户消息包含关键词时才注入。例如：用户说「去公园」，才会注入公园的描述。',
      constant: '<strong>每轮常驻</strong>：不需要关键词，每轮对话都注入。例如：角色的职业背景，需要AI时刻记住。Sticky/Cooldown不适用。',
      always: '<strong>始终注入</strong>：无论什么情况都注入。例如：世界观的基础规则，必须一直存在。',
    };
    hint.innerHTML = hints[mode] || '';
  });

  // 确认弹窗确认按钮
  const confirmOk = document.getElementById('confirm-modal-ok');
  if (confirmOk) confirmOk.addEventListener('click', () => closeConfirmModal(true));
}

function bindFabSaveFallback(handlePrimaryAction) {
  const fab = document.getElementById('fab-save');
  if (!fab) return;
  fab.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    handlePrimaryAction('save-char', fab);
  });
}

function bindKeyboardShortcuts(handlePrimaryAction) {
  document.addEventListener('keydown', (event) => {
    // Ctrl/Cmd+S 保存
    if ((event.ctrlKey || event.metaKey) && event.key === 's') {
      event.preventDefault();
      if (AdminState.currentCharId && AdminState.currentCharTab === 'edit') {
        handlePrimaryAction('save-char', null);
      }
      return;
    }
    // Arrow Up/Down 在角色列表间导航
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      const items = [...document.querySelectorAll('.char-item')];
      if (!items.length) return;
      const current = document.activeElement?.closest('.char-item');
      const idx = current ? items.indexOf(current) : -1;
      if (idx === -1 && event.key === 'ArrowDown') { items[0]?.focus(); event.preventDefault(); return; }
      const next = event.key === 'ArrowDown' ? Math.min(idx + 1, items.length - 1) : Math.max(idx - 1, 0);
      items[next]?.focus();
      event.preventDefault();
      return;
    }
    // Enter 在角色列表项上触发选择
    if (event.key === 'Enter' && document.activeElement?.classList.contains('char-item')) {
      const charId = document.activeElement.dataset.charId;
      if (charId) handlePrimaryAction('select-char', document.activeElement);
      event.preventDefault();
      return;
    }
    // ESC 关闭弹窗
    if (event.key === 'Escape') {
      const modals = document.querySelectorAll('.modal');
      for (let i = modals.length - 1; i >= 0; i--) {
        const m = modals[i];
        if (m.style.display === 'flex') {
          if (m.id === 'confirm-modal') { closeConfirmModal(false); }
          else { m.style.display = 'none'; }
          event.preventDefault();
          return;
        }
      }
    }
  });
}

function bootstrapAdminApp(handlePrimaryAction) {
  bindAdminDelegatedEvents(handlePrimaryAction);
  bindAdminInputEvents();
  bindFabSaveFallback(handlePrimaryAction);
  bindKeyboardShortcuts(handlePrimaryAction);
  AdminAPI.bootstrapAdminPage().then(ok => {
    if (!ok) return;
    loadCharList().then(() => {
      // 从 URL hash 恢复标签页位置
      _restoreFromHash();
    });
  });
}

/** 从 URL hash 恢复标签页状态 */
function _restoreFromHash() {
  const hash = (location.hash || '').replace(/^#/, '');
  if (!hash) return;

  // 系统标签页: #dashboard / #membership / #auditlog
  if (SYSTEM_TABS.includes(hash)) {
    switchSystemTab(hash);
    return;
  }
  // 角色标签页: #char/{charId}/{tab}
  const charMatch = hash.match(/^char\/([^/]+)\/?(\w*)$/);
  if (charMatch) {
    const [, charId, tab] = charMatch;
    const validTab = CHAR_TABS.includes(tab) ? tab : 'overview';
    selectChar(charId).then(() => {
      if (validTab !== 'overview') switchCharTab(validTab);
    });
  }
}
