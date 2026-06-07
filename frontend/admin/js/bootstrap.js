/**
 * bootstrap.js - 启动绑定逻辑
 * 重构版：5个角色标签 + 3个系统标签 + 顶栏导航 + ESC关闭弹窗
 */

// ============================================================
// 标签切换
// ============================================================
const CHAR_TABS = ['overview', 'edit', 'worldinfo', 'story', 'preview'];
const SYSTEM_TABS = ['dashboard', 'membership', 'auditlog'];

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

  CHAR_TABS.forEach(t => {
    const el = document.getElementById(`tab-${t}`);
    if (el) el.style.display = t === tab ? '' : 'none';
  });
  SYSTEM_TABS.forEach(t => {
    const el = document.getElementById(`tab-${t}`);
    if (el) el.style.display = 'none';
  });

  if (tab === 'worldinfo' && AdminState.currentCharId) loadAdvancedData();
  if (tab === 'story' && AdminState.currentCharId) loadAdvancedData();
  if (tab === 'preview' && AdminState.currentCharId) loadPromptPreview();
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

  CHAR_TABS.forEach(t => {
    const el = document.getElementById(`tab-${t}`);
    if (el) el.style.display = 'none';
  });
  SYSTEM_TABS.forEach(t => {
    const el = document.getElementById(`tab-${t}`);
    if (el) el.style.display = t === tab ? '' : 'none';
  });

  if (tab === 'membership') loadMembershipData();
  if (tab === 'dashboard') loadDashboard();
  if (tab === 'auditlog') loadAuditLogs();
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

function bindKeyboardShortcuts() {
  document.addEventListener('keydown', (event) => {
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
  bindKeyboardShortcuts();
  AdminAPI.bootstrapAdminPage().then(ok => {
    if (ok) loadCharList();
  });
}
