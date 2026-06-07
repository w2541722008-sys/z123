/**
 * state.js - 全局共享状态
 * 重构版：新增世界书/剧情标签相关状态
 */
const AdminState = (() => {
  // ---- 角色相关 ----
  let _currentCharId = null;
  let _currentCharData = null;
  let _currentCharSummary = null;
  let _currentPromptPreview = null;
  let _allCharsCache = [];

  // ---- 高级配置相关 ----
  let _currentCharTab = 'overview';
  let _advancedData = { memories: [], categories: [], greetings: [], storylines: [], postRules: [], events: [] };
  let _currentGreetingFilter = 'all';

  // ---- 记忆筛选 ----
  let _memorySearchQuery = '';
  let _memoryFilterCategory = 'all';
  let _memoryFilterStatus = 'all';
  let _memoryFilterMode = 'all';

  // ---- 会员管理相关 ----
  let _membershipData = {
    users: [], orders: [], usersTotal: 0, ordersTotal: 0,
    usersPage: 1, ordersPage: 1, usersLimit: 20, ordersLimit: 20,
    selectedUserIds: new Set(),
  };

  // ---- 操作日志 ----
  let _auditPage = 1;

  // ---- 编辑面板 ----
  let _currentRlFields = [];

  // ---- 编辑面板脏标记（未保存修改） ----
  let _isDirty = false;

  // ---- 保存中锁（防止重复提交） ----
  let _isSaving = false;

  // ---- 待删除用户 ----
  let _pendingDeleteUserId = null;

  // ---- 系统标签 ----
  let _currentSystemTab = null;

  // ---- 自定义确认弹窗 ----
  let _confirmResolver = null;

  return {
    get currentCharId() { return _currentCharId; },
    set currentCharId(v) { _currentCharId = v; },
    get currentCharData() { return _currentCharData; },
    set currentCharData(v) { _currentCharData = v; },
    get currentCharSummary() { return _currentCharSummary; },
    set currentCharSummary(v) { _currentCharSummary = v; },
    get currentPromptPreview() { return _currentPromptPreview; },
    set currentPromptPreview(v) { _currentPromptPreview = v; },
    get allCharsCache() { return _allCharsCache; },
    set allCharsCache(v) { _allCharsCache = v; },

    get currentCharTab() { return _currentCharTab; },
    set currentCharTab(v) { _currentCharTab = v; },
    get advancedData() { return _advancedData; },
    set advancedData(v) { _advancedData = v; },
    get currentGreetingFilter() { return _currentGreetingFilter; },
    set currentGreetingFilter(v) { _currentGreetingFilter = v; },

    get memorySearchQuery() { return _memorySearchQuery; },
    set memorySearchQuery(v) { _memorySearchQuery = v; },
    get memoryFilterCategory() { return _memoryFilterCategory; },
    set memoryFilterCategory(v) { _memoryFilterCategory = v; },
    get memoryFilterStatus() { return _memoryFilterStatus; },
    set memoryFilterStatus(v) { _memoryFilterStatus = v; },
    get memoryFilterMode() { return _memoryFilterMode; },
    set memoryFilterMode(v) { _memoryFilterMode = v; },

    get membershipData() { return _membershipData; },
    get auditPage() { return _auditPage; },
    set auditPage(v) { _auditPage = v; },
    get currentRlFields() { return _currentRlFields; },
    set currentRlFields(v) { _currentRlFields = v; },
    get pendingDeleteUserId() { return _pendingDeleteUserId; },
    set pendingDeleteUserId(v) { _pendingDeleteUserId = v; },

    get isDirty() { return _isDirty; },
    set isDirty(v) { _isDirty = v; },

    get isSaving() { return _isSaving; },
    set isSaving(v) { _isSaving = v; },

    get currentSystemTab() { return _currentSystemTab; },
    set currentSystemTab(v) { _currentSystemTab = v; },
    get confirmResolver() { return _confirmResolver; },
    set confirmResolver(v) { _confirmResolver = v; },
  };
})();
