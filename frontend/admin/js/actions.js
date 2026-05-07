const CHARACTER_ACTION_HANDLERS = {
  'load-char-list': () => loadCharList(),
  'open-create-char-modal': () => openCreateCharModal(),
  'close-create-char-modal': () => closeCreateCharModal(),
  'create-character': () => createCharacter(),
  'save-char': () => saveChar(),
  'delete-current-character': () => deleteCurrentCharacter(),
  'add-affection-custom-row': () => addAffectionCustomRow(),
  'remove-affection-custom-row': (trigger) => removeAffectionCustomRow(trigger),
  'reset-affection-rules': () => resetAffectionRulesEditor(),
  'toggle-beginner-mode': () => toggleBeginnerMode(),
  'hide-guide': () => hideGuide(),
  'select-char': (trigger) => {
    if (trigger.dataset.charId) selectChar(trigger.dataset.charId);
  },
};

const ADVANCED_ACTION_HANDLERS = {
  'open-memory-modal': () => openMemoryModal(),
  'close-memory-modal': () => closeMemoryModal(),
  'save-memory': () => saveMemory(),
  'delete-memory': () => deleteMemory(),
  'open-greeting-modal': () => openGreetingModal(),
  'filter-greetings': (trigger) => filterGreetings(trigger.dataset.phase || 'all'),
  'close-greeting-modal': () => closeGreetingModal(),
  'save-greeting': () => saveGreeting(),
  'delete-greeting': () => deleteGreeting(),
  'open-storyline-modal': () => openStorylineModal(),
  'close-storyline-modal': () => closeStorylineModal(),
  'save-storyline': () => saveStoryline(),
  'delete-storyline': () => deleteStoryline(),
  'open-category-modal': () => openCategoryModal(),
  'close-category-modal': () => closeCategoryModal(),
  'save-category': () => saveCategory(),
  'delete-category': () => deleteCategory(),
  'open-postrule-modal': () => openPostRuleModal(),
  'close-postrule-modal': () => closePostRuleModal(),
  'save-postrule': () => savePostRule(),
  'delete-postrule': () => deletePostRule(),
  'open-event-modal': () => openEventModal(),
  'close-event-modal': () => closeEventModal(),
  'save-event': () => saveEvent(),
  'delete-event': () => deleteEvent(),
  'edit-memory': (trigger) => editMemory(trigger.dataset.id || ''),
  'edit-greeting': (trigger) => editGreeting(trigger.dataset.id || ''),
  'edit-storyline': (trigger) => editStoryline(trigger.dataset.id || ''),
  'edit-category': (trigger) => editCategory(trigger.dataset.id || ''),
  'edit-postrule': (trigger) => editPostRule(trigger.dataset.id || ''),
  'edit-event': (trigger) => editEvent(trigger.dataset.id || ''),
  'test-keywords': () => testKeywords(),
  'load-prompt-preview': () => loadPromptPreview(),
  'copy-prompt-preview': () => copyPromptPreview(),
  'close-confirm-modal': () => closeConfirmModal(false),
};

const MEMBERSHIP_ACTION_HANDLERS = {
  'load-membership-data': () => loadMembershipData(),
  'batch-update-plan': () => batchUpdatePlan(),
  'clear-user-selection': () => clearUserSelection(),
  'close-user-detail-modal': () => closeUserDetailModal(),
  'close-user-edit-modal': () => closeUserEditModal(),
  'save-user-edit': () => saveUserEdit(),
  'open-user-detail': (trigger) => openUserDetail(trigger.dataset.userId || ''),
  'open-user-edit': (trigger) => openUserEdit(trigger.dataset.userId || ''),
  'confirm-delete-user': (trigger) => confirmDeleteUser(trigger.dataset.userId || '', trigger.dataset.userEmail || ''),
  'close-order-detail-modal': () => closeOrderDetailModal(),
  'open-order-detail': (trigger) => openOrderDetail(trigger.dataset.orderId || ''),
  'export-users-csv': () => exportUsersCSV(),
  'export-orders-csv': () => exportOrdersCSV(),
};

const DASHBOARD_ACTION_HANDLERS = {
  'load-dashboard': () => loadDashboard(),
  'load-media-missing': (trigger) => loadMediaMissing((trigger?.dataset?.refresh || 'false') === 'true'),
  'load-audit-logs': () => loadAuditLogs(),
  'admin-reload': () => location.reload(),
  'switch-system-tab': (trigger) => switchSystemTab(trigger.dataset.tab || 'dashboard'),
};

const ACTION_HANDLERS = {
  ...CHARACTER_ACTION_HANDLERS,
  ...ADVANCED_ACTION_HANDLERS,
  ...MEMBERSHIP_ACTION_HANDLERS,
  ...DASHBOARD_ACTION_HANDLERS,
};

function handlePrimaryAction(action, trigger) {
  const handler = ACTION_HANDLERS[action];
  if (!handler) return false;
  handler(trigger);
  return true;
}
