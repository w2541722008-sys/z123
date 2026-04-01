/**
 * state.js - 全局共享状态
 * 
 * 各模块之间共享的可变状态集中管理。
 * 每个模块通过 AdminState 读写状态，避免到处散落 let 变量。
 */
const AdminState = (() => {
  // ---- 角色相关 ----
  let _currentCharId = null;
  let _currentCharData = null;
  let _currentCharSummary = null;
  let _currentPromptPreview = null;
  let _allCharsCache = [];

  // ---- 高级配置相关 ----
  let _currentAdvancedTab = 'memories';
  let _advancedData = { memories: [], categories: [], greetings: [], storylines: [], postRules: [], events: [] };
  let _currentGreetingFilter = 'all';

  // ---- 会员管理相关 ----
  let _membershipData = {
    users: [],
    orders: [],
    usersTotal: 0,
    ordersTotal: 0,
    usersPage: 1,
    ordersPage: 1,
    usersLimit: 20,
    ordersLimit: 20,
    selectedUserIds: new Set(),
  };

  // ---- 操作日志 ----
  let _auditPage = 1;

  // ---- 编辑面板 ----
  let _currentRlFields = [];

  // ---- 待删除用户（临时状态） ----
  let _pendingDeleteUserId = null;

  return {
    // 角色相关
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

    // 高级配置
    get currentAdvancedTab() { return _currentAdvancedTab; },
    set currentAdvancedTab(v) { _currentAdvancedTab = v; },
    get advancedData() { return _advancedData; },
    set advancedData(v) { _advancedData = v; },
    get currentGreetingFilter() { return _currentGreetingFilter; },
    set currentGreetingFilter(v) { _currentGreetingFilter = v; },

    // 会员管理
    get membershipData() { return _membershipData; },

    // 操作日志
    get auditPage() { return _auditPage; },
    set auditPage(v) { _auditPage = v; },

    // 编辑面板
    get currentRlFields() { return _currentRlFields; },
    set currentRlFields(v) { _currentRlFields = v; },

    // 临时删除状态
    get pendingDeleteUserId() { return _pendingDeleteUserId; },
    set pendingDeleteUserId(v) { _pendingDeleteUserId = v; },
  };
})();
