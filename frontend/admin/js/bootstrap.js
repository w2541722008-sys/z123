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

    const tabTrigger = event.target.closest('.tabs .tab-btn[data-tab]');
    if (tabTrigger) {
      event.preventDefault();
      switchTab(tabTrigger.dataset.tab);
    }
  });
}

function bindAdminInputEvents() {
  const bind = (id, eventName, handler) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener(eventName, handler);
  };

  bind('char-filter-search', 'input', () => renderCharListSidebar());
  bind('char-filter-visible', 'change', () => renderCharListSidebar());
  bind('char-filter-type', 'change', () => renderCharListSidebar());

  bind('user-search', 'input', () => filterUsers());
  bind('user-plan-filter', 'change', () => filterUsers());

  bind('order-search', 'input', () => debouncedFilterOrders());
  bind('order-status-filter', 'change', () => filterOrders());

  bind('audit-action-filter', 'change', () => loadAuditLogs());
}

function bindFabSaveFallback(handlePrimaryAction) {
  const fab = document.getElementById('fab-save');
  if (!fab) return;
  const triggerSave = (event) => {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    handlePrimaryAction('save-char', fab);
  };

  fab.addEventListener('click', triggerSave, true);
  fab.addEventListener('pointerup', triggerSave, true);

  const btn = fab.querySelector('button[data-action="save-char"]');
  if (btn) {
    btn.type = 'button';
    btn.addEventListener('click', triggerSave, true);
    btn.addEventListener('pointerup', triggerSave, true);
  }

  const label = document.getElementById('fab-label');
  if (label) {
    label.tabIndex = 0;
    label.addEventListener('click', triggerSave, true);
    label.addEventListener('pointerup', triggerSave, true);
    label.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        triggerSave(event);
      }
    });
  }
}

function bootstrapAdminApp(handlePrimaryAction) {
  bindAdminDelegatedEvents(handlePrimaryAction);
  bindAdminInputEvents();
  bindFabSaveFallback(handlePrimaryAction);
  AdminAPI.bootstrapAdminPage().then(ok => {
    if (ok) {
      loadCharList();
    }
  });
}
