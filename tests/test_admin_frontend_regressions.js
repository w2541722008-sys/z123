/**
 * 管理后台前端回归测试
 *
 * 运行方式：node tests/test_admin_frontend_regressions.js
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');

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
        toggle(name, value) {
          this.toggles.push([name, value]);
        },
      },
      querySelector() {
        return null;
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

  assert.match(context.document.get('storylines-list').innerHTML, /解锁沉浸度: 30/);
  assert.match(context.document.get('events-list').innerHTML, /沉浸度 >= 50/);

  const modals = readProjectFile('frontend/admin/partials/modals.html');
  assert.ok(!modals.includes('解锁好感度'));
  assert.ok(!modals.includes('触发好感度'));
  assert.ok(modals.includes('解锁分数'));
  assert.ok(modals.includes('触发分数'));
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

testAdvancedEditorsAcceptStringDomIds();
testScenarioScoreCopyUsesImmersion();
testClearUserSelectionHandlesMissingCheckAll();
testDownloadCsvPreservesZeroValues();

console.log('✅ 管理后台前端回归测试全部通过');
