/**
 * 管理后台前端回归测试
 *
 * 运行方式：node tests/test_admin_frontend_regressions.js
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..', '..');

function readProjectFile(relativePath) {
  return fs.readFileSync(path.join(ROOT, relativePath), 'utf8');
}

function createDocumentStub({ missingIds = new Set() } = {}) {
  const elements = new Map();

  function makeElement(id) {
    return {
      id,
      value: '',
      checked: false,
      textContent: '',
      innerHTML: '',
      dataset: {},
      disabled: false,
      style: {},
      classList: {
        toggles: [],
        add() {},
        remove() {},
        toggle(name, value) {
          this.toggles.push([name, value]);
        },
      },
      querySelector() {
        if (this.innerHTML.includes('value=""')) {
          return { value: '' };
        }
        return null;
      },
      querySelectorAll(selector) {
        if (selector !== 'input[type="checkbox"]:checked') return [];
        return this.checkedValues ? this.checkedValues.map((value) => ({ value })) : [];
      },
      addEventListener() {},
      click() {},
    };
  }

  return {
    elements,
    get(id) {
      if (!elements.has(id)) elements.set(id, makeElement(id));
      return elements.get(id);
    },
    getElementById(id) {
      if (missingIds.has(id)) return null;
      return this.get(id);
    },
    querySelector() {
      return null;
    },
    querySelectorAll() {
      return [];
    },
    createElement(tag) {
      return makeElement(tag);
    },
    body: {
      appendChild() {},
    },
  };
}

function createAdminScriptContext(scriptPath, extra = {}) {
  const context = vm.createContext({
    console,
    AdminState: {
      currentCharId: 'luna',
      currentCharData: { card_type: 'scenario', affection_enabled: true },
      advancedData: {
        memories: [],
        categories: [],
        greetings: [],
        storylines: [],
        postRules: [],
        events: [],
      },
      currentGreetingFilter: 'all',
      memorySearchQuery: '',
      memoryFilterCategory: 'all',
      memoryFilterStatus: 'all',
      memoryFilterMode: 'all',
      membershipData: { selectedUserIds: new Set() },
    },
    AdminAPI: { API: '/api/admin', apiFetch: async () => [] },
    document: createDocumentStub(),
    window: { AIFriendShared: { escapeHtml: (value) => String(value ?? '') } },
    Blob,
    URL: {
      createObjectURL() {
        return 'blob:test';
      },
      revokeObjectURL() {},
    },
    URLSearchParams,
    requestAnimationFrame(fn) {
      fn();
    },
    setTimeout(fn) {
      fn();
    },
    toast() {},
    showConfirm: async () => true,
    escHtml(value) {
      return String(value ?? '');
    },
    formatDate(value) {
      return String(value ?? '');
    },
    splitCsvIds(raw) {
      return String(raw || '')
        .split(',')
        .map((x) => x.trim())
        .filter(Boolean);
    },
    getCheckedValues() {
      return [];
    },
    debounce(fn) {
      return fn;
    },
    skeletonHtml() {
      return '';
    },
    renderPager() {},
    formatPlanLabel(value) {
      return value || '';
    },
    ...extra,
  });
  vm.runInContext(readProjectFile(scriptPath), context, { filename: scriptPath });
  return context;
}

function getUrlQueryParams(rawUrl) {
  const url = new URL(rawUrl, 'http://admin.test');
  return url.searchParams;
}

function testAdvancedEditorsAcceptStringDomIds() {
  const context = createAdminScriptContext('frontend/admin/js/char-advanced.js');
  context.AdminState.advancedData = {
    memories: [{
      id: 1,
      keywords: 'keyword',
      trigger_logic: 'any',
      content: 'content',
      category_id: null,
      position: 'before',
      priority: 100,
      comment: '',
      is_active: true,
      selective: true,
      constant: false,
      sticky: 0,
      cooldown: 0,
    }],
    categories: [{
      id: 2,
      name: 'category',
      description: '',
      color: '#1890FF',
      sort_order: 0,
      created_at: '',
    }],
    greetings: [{
      id: 3,
      story_phase: 'stranger',
      mood: 'neutral',
      content: 'hello',
      storyline_id: null,
      priority: 100,
      is_active: true,
      use_count: 0,
    }],
    storylines: [{
      id: 4,
      name: 'main',
      description: '',
      unlock_score: 0,
      sort_order: 0,
      is_default: true,
      is_active: true,
    }],
    postRules: [{
      id: 5,
      name: 'rule',
      content: 'content',
      storyline_id: null,
      story_phase: '',
      priority: 100,
      is_active: true,
    }],
    events: [{
      id: 6,
      title: 'event',
      description: '',
      trigger_score: 20,
      unlocked_memory_ids: '',
      unlocked_greeting_ids: '',
      unlocked_storyline_id: null,
      event_content: 'content',
      sort_order: 0,
      is_active: true,
    }],
  };

  context.editMemory('1');
  context.editCategory('2');
  context.editGreeting('3');
  context.editStoryline('4');
  context.editPostRule('5');
  context.editEvent('6');

  assert.strictEqual(String(context.document.get('memory-id').value), '1');
  assert.strictEqual(String(context.document.get('category-id').value), '2');
  assert.strictEqual(String(context.document.get('greeting-id').value), '3');
  assert.strictEqual(String(context.document.get('storyline-id').value), '4');
  assert.strictEqual(String(context.document.get('postrule-id').value), '5');
  assert.strictEqual(String(context.document.get('event-id').value), '6');
}

function testScenarioScoreCopyUsesImmersion() {
  const context = createAdminScriptContext('frontend/admin/js/char-advanced.js');
  context.AdminState.currentCharData = { card_type: 'scenario', affection_enabled: true };
  context.AdminState.advancedData.storylines = [{
    id: 1,
    name: '主线',
    description: '',
    unlock_score: 30,
    sort_order: 0,
    is_default: false,
    is_active: true,
  }];
  context.AdminState.advancedData.events = [{
    id: 2,
    title: '事件',
    description: '',
    trigger_score: 50,
    unlocked_memory_ids: '',
    unlocked_greeting_ids: '',
    unlocked_storyline_id: null,
    event_content: '',
    sort_order: 0,
    is_active: true,
  }];

  context.renderStorylines();
  context.renderEvents();

  assert.match(context.document.get('storylines-list').innerHTML, /沉浸度门槛: 30/);
  assert.match(context.document.get('events-list').innerHTML, /沉浸度 >= 50/);

  const modals = readProjectFile('frontend/admin/partials/modals.html');
  assert.ok(!modals.includes('解锁好感度'));
  assert.ok(!modals.includes('触发好感度'));
  assert.ok(modals.includes('解锁分数'));
  assert.ok(modals.includes('触发分数'));
}

function testStoryCopyUsesEnableTerminology() {
  const overview = readProjectFile('frontend/admin/js/overview.js');
  const config = readProjectFile('frontend/admin/js/config.js');
  const advanced = readProjectFile('frontend/admin/js/char-advanced.js');

  assert.ok(overview.includes('触发后启用内容'));
  assert.ok(config.includes('触发后启用内容'));
  assert.ok(advanced.includes('事件触发后将启用以上内容'));
  assert.ok(!overview.includes('解锁内容'));
  assert.ok(!config.includes('解锁内容'));
}

async function testPostRulePhaseCanStayGlobal() {
  let savedPayload = null;
  const context = createAdminScriptContext('frontend/admin/js/char-advanced.js', {
    AdminAPI: {
      API: '/api/admin',
      apiFetch: async (_url, options) => {
        if (options?.body) savedPayload = JSON.parse(options.body);
        return { ok: true };
      },
    },
  });

  context.openPostRuleModal();
  assert.match(context.document.get('postrule-phase').innerHTML, /value="">全部阶段/);
  assert.strictEqual(context.document.get('postrule-phase').value, '');

  context.document.get('postrule-name').value = '通用规则';
  context.document.get('postrule-content').value = '每轮都要遵守';
  await context.savePostRule();

  assert.strictEqual(savedPayload.story_phase, null);
}

async function testStoryEventPreservesCustomTriggerKey() {
  let savedPayload = null;
  const context = createAdminScriptContext('frontend/admin/js/char-advanced.js', {
    AdminAPI: {
      API: '/api/admin',
      apiFetch: async (_url, options) => {
        if (options?.body) savedPayload = JSON.parse(options.body);
        return { ok: true };
      },
    },
    getCheckedValues(id) {
      return context.document.get(id).checkedValues || [];
    },
  });
  context.AdminState.advancedData.events = [{
    id: 9,
    title: '找到钥匙',
    description: '',
    trigger_score: 20,
    trigger_custom_key: 'has_key',
    unlocked_memory_ids: '',
    unlocked_greeting_ids: '',
    unlocked_storyline_id: null,
    event_content: '引导用户开门',
    sort_order: 0,
    is_active: true,
  }];

  context.editEvent('9');
  assert.strictEqual(context.document.get('event-trigger-custom-key').value, 'has_key');
  await context.saveEvent();

  assert.strictEqual(savedPayload.trigger_custom_key, 'has_key');
}

function testEventSelectorsIncludeInactiveAssetsAsPendingEnable() {
  const context = createAdminScriptContext('frontend/admin/js/char-advanced.js');
  context.AdminState.advancedData = {
    memories: [
      { id: 1, keywords: '启用记忆', content: 'A', comment: '', is_active: true },
      { id: 2, keywords: '待启用记忆', content: 'B', comment: '', is_active: false },
    ],
    greetings: [
      { id: 3, story_phase: 'stranger', mood: 'neutral', content: '你好', is_active: true },
      { id: 4, story_phase: 'friend', mood: 'warm', content: '欢迎回来', is_active: false },
    ],
    storylines: [
      { id: 5, name: '主线', is_active: true },
      { id: 6, name: '隐藏线', is_active: false },
    ],
    categories: [],
    postRules: [],
    events: [],
  };

  context.renderEventSelectors(['2'], ['4'], '6');

  assert.match(context.document.get('event-memory-selector').innerHTML, /待启用记忆/);
  assert.match(context.document.get('event-memory-selector').innerHTML, /触发后启用/);
  assert.match(context.document.get('event-greeting-selector').innerHTML, /欢迎回来/);
  assert.match(context.document.get('event-storyline-id').innerHTML, /隐藏线/);
}

async function testStorylineAdvancedFieldsArePreserved() {
  let savedPayload = null;
  const context = createAdminScriptContext('frontend/admin/js/char-advanced.js', {
    AdminAPI: {
      API: '/api/admin',
      apiFetch: async (_url, options) => {
        if (options?.body) savedPayload = JSON.parse(options.body);
        return { ok: true };
      },
    },
  });
  context.AdminState.advancedData.storylines = [{
    id: 7,
    storyline_id: 'route_hidden',
    title: '隐藏路线标题',
    name: '隐藏线',
    description: '描述',
    unlock_score: 40,
    unlock_condition: '拿到钥匙',
    stages: ['初遇', '抉择'],
    sort_order: 1,
    is_default: false,
    is_active: true,
  }];

  context.editStoryline('7');
  await context.saveStoryline();

  assert.strictEqual(savedPayload.storyline_id, 'route_hidden');
  assert.strictEqual(savedPayload.title, '隐藏路线标题');
  assert.strictEqual(savedPayload.unlock_condition, '拿到钥匙');
  assert.deepStrictEqual(savedPayload.stages, ['初遇', '抉择']);
}

async function testPromptPreviewSendsSimulatorInputs() {
  let requestedUrl = '';
  const context = createAdminScriptContext('frontend/admin/js/prompt-preview.js', {
    AdminAPI: {
      API: '/api/admin',
      apiFetch: async (url) => {
        requestedUrl = url;
        return {
          messages: [{ role: 'system', content: '系统预览' }],
          preview_summary: {
            has_sample_user_message: true,
            has_world_info: true,
            has_post_rules: true,
            has_state_snapshot: true,
          },
        };
      },
    },
  });
  context.AdminState.currentCharId = 'luna';
  context.document.get('prompt-preview-sample').value = '地下室钥匙';
  context.document.get('prompt-preview-affection').value = '66';
  context.document.get('prompt-preview-phase').value = 'friend';
  context.document.get('prompt-preview-mood').value = 'warm';
  context.document.get('prompt-preview-storyline').value = '7';
  context.document.get('prompt-preview-custom-vars').value = '{"has_key":true}';

  await context.loadPromptPreview();

  const params = getUrlQueryParams(requestedUrl);
  assert.strictEqual(params.get('sample_user_message'), '地下室钥匙');
  assert.strictEqual(params.get('affection'), '66');
  assert.strictEqual(params.get('story_phase'), 'friend');
  assert.strictEqual(params.get('mood'), 'warm');
  assert.strictEqual(params.get('storyline_id'), '7');
  assert.strictEqual(params.get('custom_vars_json'), '{"has_key":true}');
  assert.match(context.document.get('prompt-preview-content').innerHTML, /命中摘要/);
}

async function testPromptPreviewInvalidCustomVarsBlocksRequest() {
  let requestCount = 0;
  const context = createAdminScriptContext('frontend/admin/js/prompt-preview.js', {
    AdminAPI: {
      API: '/api/admin',
      apiFetch: async () => {
        requestCount += 1;
        return { messages: [] };
      },
    },
  });
  context.AdminState.currentCharId = 'luna';
  context.document.get('prompt-preview-custom-vars').value = '{"broken"';

  await context.loadPromptPreview();

  assert.strictEqual(requestCount, 0);
  assert.match(context.document.get('prompt-preview-content').innerHTML, /自定义变量 JSON 格式错误/);
}

function testOverviewUsesBackendAuthoritativeEventStats() {
  const context = createAdminScriptContext('frontend/admin/js/overview.js');
  context.AdminState.currentCharData = {
    name: '露娜',
    system_prompt: '你是露娜',
    affection_enabled: 1,
    affection_rules_json: '{"enabled":true}',
  };
  context.AdminState.advancedData.events = [];
  context.renderCharacterOverview({
    name: '露娜',
    subtitle: '',
    completeness: 70,
    default_storyline_id: 1,
    warnings: [],
    stats: {
      memories: 3,
      active_memories: 3,
      greetings: 2,
      active_greetings: 2,
      greeting_phase_coverage: 2,
      storylines: 1,
      active_storylines: 1,
      post_rules: 1,
      active_post_rules: 1,
      events: 2,
      active_events: 2,
      empty_enable_events: 1,
      empty_event_content_events: 1,
    },
  });

  const html = context.document.get('tab-overview').innerHTML;
  assert.match(html, /缺启用内容 1 \/ 缺文案 1/);
  assert.match(html, /当前还有 1 个事件缺触发后启用内容、1 个事件缺触发文案/);
}

function testOverviewDoesNotRequireAdvancedDataForDefaultStorylineWarning() {
  const context = createAdminScriptContext('frontend/admin/js/overview.js');
  context.AdminState.currentCharData = {
    name: '露娜',
    system_prompt: '你是露娜',
    affection_enabled: 0,
    affection_rules_json: '{}',
  };
  context.AdminState.advancedData.storylines = [];
  context.renderCharacterOverview({
    name: '露娜',
    subtitle: '',
    completeness: 60,
    default_storyline_id: null,
    warnings: [],
    stats: {
      memories: 3,
      active_memories: 3,
      greetings: 2,
      active_greetings: 2,
      greeting_phase_coverage: 2,
      storylines: 1,
      active_storylines: 1,
      post_rules: 0,
      active_post_rules: 0,
      events: 0,
      active_events: 0,
      empty_enable_events: 0,
      empty_event_content_events: 0,
    },
  });

  const html = context.document.get('tab-overview').innerHTML;
  assert.match(html, /已有剧情线，但还没有设置默认剧情线/);
}

function testChatStreamUsesEnableTerminologyForStoryEvents() {
  const source = readProjectFile('frontend/modules/chat-stream.js');
  assert.ok(source.includes('启用记忆'));
  assert.ok(source.includes('启用开场白'));
  assert.ok(source.includes('启用新剧情线'));
  assert.ok(source.includes('剧情已启用'));
  assert.ok(!source.includes('解锁记忆'));
  assert.ok(!source.includes('解锁开场白'));
  assert.ok(!source.includes('解锁新剧情线'));
  assert.ok(!source.includes('剧情已解锁'));
}

function testGreetingMoodOptionsMatchBackendEnum() {
  const modals = readProjectFile('frontend/admin/partials/modals.html');
  const moodSelect = modals.match(/<select id="greeting-mood"[\s\S]*?<\/select>/);
  assert.ok(moodSelect, 'missing greeting mood select');
  const uiMoods = new Set([...moodSelect[0].matchAll(/<option value="([^"]+)">/g)].map((match) => match[1]));
  const moodPy = readProjectFile('backend/constants/mood.py');
  const backendMoods = new Set([...moodPy.matchAll(/= "([^"]+)"/g)].map((match) => match[1]));

  assert.deepStrictEqual([...uiMoods].sort(), [...backendMoods].sort());
  assert.ok(!uiMoods.has('flirty'));
}

function testClearUserSelectionHandlesMissingCheckAll() {
  const document = createDocumentStub({ missingIds: new Set(['user-check-all']) });
  const context = createAdminScriptContext('frontend/admin/js/membership.js', { document });
  context.AdminState.membershipData.selectedUserIds.add('1');

  assert.doesNotThrow(() => context.clearUserSelection());
  assert.strictEqual(context.AdminState.membershipData.selectedUserIds.size, 0);
}

function testDownloadCsvPreservesZeroValues() {
  let blobText = '';
  const document = createDocumentStub();
  const context = createAdminScriptContext('frontend/admin/js/utils.js', {
    document,
    Blob: class FakeBlob {
      constructor(parts) {
        blobText = parts.join('');
      }
    },
  });

  context.downloadCSV('users.csv', [['id', 'count'], [1, 0]]);

  assert.ok(blobText.includes('"0"'), blobText);
}

function extractBackendAuditActions() {
  const dir = path.join(ROOT, 'backend/routers/admin');
  const actions = new Set();

  function walk(currentDir) {
    for (const name of fs.readdirSync(currentDir)) {
      const fullPath = path.join(currentDir, name);
      const stat = fs.statSync(fullPath);
      if (stat.isDirectory()) {
        if (name !== '__pycache__') walk(fullPath);
        continue;
      }
      if (!name.endsWith('.py')) continue;
      const source = fs.readFileSync(fullPath, 'utf8');
      for (const match of source.matchAll(/action="([^"]+)"/g)) {
        actions.add(match[1]);
      }
    }
  }

  walk(dir);
  return actions;
}

function testAuditLogCoversAllBackendActions() {
  const backendActions = extractBackendAuditActions();
  const panelHtml = readProjectFile('frontend/admin/partials/system-panels.html');
  const auditJs = readProjectFile('frontend/admin/js/audit-log.js');
  const filterActions = new Set(
    [...panelHtml.matchAll(/<option value="([a-z_]+)">/g)].map((match) => match[1])
  );
  const displayActions = new Set(
    [...auditJs.matchAll(/\b([a-z]+_[a-z_]+): \[['"][^'"]+['"], ['"][^'"]+['"]\]/g)].map((match) => match[1])
  );

  const missingFilters = [...backendActions].filter((action) => !filterActions.has(action));
  const missingLabels = [...backendActions].filter((action) => !displayActions.has(action));

  assert.deepStrictEqual(missingFilters, []);
  assert.deepStrictEqual(missingLabels, []);
}

function testOrderStatusFilterMatchesBackendEnum() {
  const constants = readProjectFile('backend/constants/order_status.py');
  const backendStatuses = new Set(
    [...constants.matchAll(/ORDER_STATUS_[A-Z_]+ = "([^"]+)"/g)].map((match) => match[1])
  );
  const panelHtml = readProjectFile('frontend/admin/partials/system-panels.html');
  const orderStatusSelect = panelHtml.match(/<select id="order-status-filter"[\s\S]*?<\/select>/);
  assert.ok(orderStatusSelect, 'missing order-status-filter select');
  const uiStatuses = new Set(
    [...orderStatusSelect[0].matchAll(/<option value="([a-z_]+)">/g)].map((match) => match[1]).filter(Boolean)
  );

  assert.deepStrictEqual([...uiStatuses].sort(), [...backendStatuses].sort());
}

function testDashboardRendersActionableConfigHealth() {
  const context = createAdminScriptContext('frontend/admin/js/dashboard.js');
  const stats = {
    total_users: 1,
    today_new_users: 0,
    paid_users: 0,
    paid_rate: 0,
    today_orders: 0,
    today_revenue: 0,
    expiring_soon: 0,
    avg_order_value: 0,
    plan_distribution: {},
    storage: { used_percent: 1, size_mb: 1, limit_mb: 500 },
  };
  const trend = { trend: [{ date: '2026-06-09', new_users: 0, new_orders: 0, revenue: 0 }] };
  const configHealth = {
    ok: false,
    summary: { ready_count: 3, warning_count: 1, error_count: 1 },
    items: [
      { key: 'runtime', label: '运行模式', status: 'ready', value: '生产模式', hint: '生产环境需要 ENV=production 且 DEBUG=false。' },
      { key: 'ai_model', label: 'AI 模型', status: 'ready', value: '已配置', hint: '未配置时聊天回复会失败。' },
      { key: 'payment', label: '支付网关', status: 'warning', value: '支付网关未接入', hint: '当前只支持订单预留、查看和导出。' },
      { key: 'email', label: '邮件服务', status: 'error', value: '未配置', hint: '未配置时找回密码验证码无法发送。' },
      { key: 'bad_class', label: '异常状态', status: 'ready onclick=alert(1)', value: '已降级', hint: '非法状态应按 warning 展示。' },
    ],
  };

  context.renderDashboard(stats, trend, { ok: true, missing_count: 0, items: [] }, configHealth);

  const html = context.document.get('dashboard-content').innerHTML;
  assert.ok(html.includes('配置健康'));
  assert.ok(html.includes('运行模式'));
  assert.ok(html.includes('AI 模型'));
  assert.ok(html.includes('支付网关未接入'));
  assert.ok(html.includes('找回密码验证码无法发送'));
  assert.ok(html.includes('config-health-item warning'));
  assert.ok(!html.includes('onclick=alert'));
  assert.ok(!html.includes('sk-secret'));
}

function testAdminAssetVersionsAreUnified() {
  const indexHtml = readProjectFile('frontend/admin/index.html');
  const adminAssets = [
    ...indexHtml.matchAll(/(?:src|href)="(\/api\/frontend\/admin\/(?:js\/[^"?]+\.js|style\.css)\?v=([^"]+))"/g),
  ];
  assert.ok(adminAssets.length > 10, 'expected admin JS/CSS assets in index.html');
  const versions = new Set(adminAssets.map((match) => match[2]));
  assert.deepStrictEqual([...versions], ['20260609b']);

  const partialsLoader = readProjectFile('frontend/admin/js/partials-loader.js');
  assert.ok(partialsLoader.includes('ADMIN_BUILD_VERSION'));
  assert.ok(partialsLoader.includes("'.html?v='"));
}

async function testSelectCharDoesNotAutoLoadPromptPreview() {
  let previewLoadCount = 0;
  const context = createAdminScriptContext('frontend/admin/js/char-list.js', {
    AdminAPI: {
      API: '/api/admin',
      apiFetch: async () => ({
        id: 'luna',
        name: '露娜',
        tags: [],
        is_visible: true,
        import_locked: false,
        affection_enabled: true,
      }),
    },
    switchCharTab: async () => {},
    normalizeCharacterDetail: (value) => value,
    renderEditPanel: () => {},
    loadCharacterSummary: () => {},
    loadPromptPreview: () => { previewLoadCount += 1; },
  });

  await context.selectChar('luna');

  assert.strictEqual(previewLoadCount, 0);
}

async function testSelectCharIgnoresStaleDetailResponse() {
  let resolveFetch;
  let renderCount = 0;
  const context = createAdminScriptContext('frontend/admin/js/char-list.js', {
    AdminAPI: {
      API: '/api/admin',
      apiFetch: async () => new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    },
    switchCharTab: async () => {},
    normalizeCharacterDetail: (value) => value,
    renderEditPanel: () => { renderCount += 1; },
    loadCharacterSummary: () => {},
    loadPromptPreview: () => {},
  });

  const promise = context.selectChar('old_char');
  context.AdminState.currentCharId = 'new_char';
  resolveFetch({
    id: 'old_char',
    name: '旧角色',
    tags: [],
    is_visible: true,
    import_locked: false,
    affection_enabled: true,
  });
  await promise;

  assert.strictEqual(renderCount, 0);
  assert.notStrictEqual(context.AdminState.currentCharData?.id, 'old_char');
}

function testPromptPreviewUsesStorylineSelect() {
  const panelHtml = readProjectFile('frontend/admin/partials/char-panels.html');
  assert.ok(panelHtml.includes('<select id="prompt-preview-storyline"'));
  assert.ok(!panelHtml.includes('type="number" id="prompt-preview-storyline"'));
}

async function testPreviewTabLoadsAdvancedDataForStorylineOptions() {
  const context = createAdminScriptContext('frontend/admin/js/bootstrap.js', {
    loadAdvancedData: () => {
      context.advancedLoadCount += 1;
    },
    loadPromptPreview: () => {
      context.previewLoadCount += 1;
    },
    history: { replaceState() {} },
    location: { hash: '' },
  });
  context.advancedLoadCount = 0;
  context.previewLoadCount = 0;
  context.AdminState.currentCharId = 'luna';

  await context.switchCharTab('preview');

  assert.strictEqual(context.advancedLoadCount, 1);
  assert.strictEqual(context.previewLoadCount, 1);
}

async function testAdvancedDataLoadReusesInFlightAndCachedRequest() {
  let requestCount = 0;
  const context = createAdminScriptContext('frontend/admin/js/char-advanced.js', {
    AdminAPI: {
      API: '/api/admin',
      apiFetch: async () => {
        requestCount += 1;
        return [];
      },
    },
  });
  context.AdminState.currentCharId = 'luna';
  context.AdminState.currentCharData = { card_type: 'scenario', affection_enabled: true };

  await Promise.all([
    context.loadAdvancedData(),
    context.loadAdvancedData(),
  ]);
  assert.strictEqual(requestCount, 6);

  await context.loadAdvancedData();
  assert.strictEqual(requestCount, 6);

  await context.loadAdvancedData({ force: true });
  assert.strictEqual(requestCount, 12);
}

async function testAdvancedDataLoadKeepsSuccessfulSectionsWhenOneRequestFails() {
  let renderCount = 0;
  let toastMessage = '';
  const context = createAdminScriptContext('frontend/admin/js/char-advanced.js', {
    AdminAPI: {
      API: '/api/admin',
      apiFetch: async (url) => {
        if (url.endsWith('/memory-categories')) {
          throw new Error('分类接口失败');
        }
        if (url.endsWith('/memories')) return [{ id: 1, keywords: '钥匙', content: '钥匙设定', is_active: true }];
        return [];
      },
    },
    toast: (message) => {
      toastMessage = message;
    },
  });
  context.AdminState.currentCharId = 'luna';
  context.AdminState.currentCharData = { card_type: 'scenario', affection_enabled: true };
  context.renderAdvancedData = () => {
    renderCount += 1;
  };

  await context.loadAdvancedData({ force: true });

  assert.strictEqual(renderCount, 1);
  assert.strictEqual(context.AdminState.advancedData.memories.length, 1);
  assert.ok(Array.isArray(context.AdminState.advancedData.categories));
  assert.strictEqual(context.AdminState.advancedData.categories.length, 0);
  assert.match(toastMessage, /部分配置加载失败/);
  assert.match(toastMessage, /记忆分类/);
}

async function run() {
  testAdvancedEditorsAcceptStringDomIds();
  testScenarioScoreCopyUsesImmersion();
  testStoryCopyUsesEnableTerminology();
  await testPostRulePhaseCanStayGlobal();
  await testStoryEventPreservesCustomTriggerKey();
  testEventSelectorsIncludeInactiveAssetsAsPendingEnable();
  await testStorylineAdvancedFieldsArePreserved();
  await testPromptPreviewSendsSimulatorInputs();
  await testPromptPreviewInvalidCustomVarsBlocksRequest();
  testOverviewUsesBackendAuthoritativeEventStats();
  testOverviewDoesNotRequireAdvancedDataForDefaultStorylineWarning();
  testChatStreamUsesEnableTerminologyForStoryEvents();
  testGreetingMoodOptionsMatchBackendEnum();
  testClearUserSelectionHandlesMissingCheckAll();
  testDownloadCsvPreservesZeroValues();
  testAuditLogCoversAllBackendActions();
  testOrderStatusFilterMatchesBackendEnum();
  testDashboardRendersActionableConfigHealth();
  testAdminAssetVersionsAreUnified();
  await testSelectCharDoesNotAutoLoadPromptPreview();
  await testSelectCharIgnoresStaleDetailResponse();
  testPromptPreviewUsesStorylineSelect();
  await testPreviewTabLoadsAdvancedDataForStorylineOptions();
  await testAdvancedDataLoadReusesInFlightAndCachedRequest();
  await testAdvancedDataLoadKeepsSuccessfulSectionsWhenOneRequestFails();

  console.log('✅ 管理后台前端回归测试全部通过');
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
