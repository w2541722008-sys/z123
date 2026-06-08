#!/usr/bin/env node
/**
 * 前端安全回归测试
 *
 * 覆盖：
 *   - 角色标签只按文字渲染，不能注入 HTML。
 *   - API base 可通过页面配置覆盖，避免静态预览强制连 8000。
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const PROJECT_DIR = path.join(__dirname, '..');

function escapeHtml(text = '') {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/\n/g, '<br/>');
}

function loadSharedUtils({
  apiBase,
  adminApiBase,
  metaApiBase,
  metaAdminApiBase,
  locationValue = { protocol: 'http:', hostname: '127.0.0.1', port: '5173' },
} = {}) {
  const code = fs.readFileSync(path.join(PROJECT_DIR, 'frontend/shared/shared-utils.js'), 'utf8');
  const context = {
    window: {},
    location: locationValue,
    document: {
      querySelector(selector) {
        if (selector === 'meta[name="aifriend-api-base"]' && metaApiBase) {
          return { content: metaApiBase };
        }
        if (selector === 'meta[name="aifriend-admin-api-base"]' && metaAdminApiBase) {
          return { content: metaAdminApiBase };
        }
        return null;
      },
    },
  };
  if (apiBase !== undefined) context.window.__API_BASE__ = apiBase;
  if (adminApiBase !== undefined) context.window.__ADMIN_API_BASE__ = adminApiBase;
  vm.createContext(context);
  vm.runInContext(code, context, { filename: 'frontend/shared/shared-utils.js' });
  return context.window.AIFriendShared;
}

function renderCharGridWithCharacters(characters) {
  const code = fs.readFileSync(path.join(PROJECT_DIR, 'frontend/modules/utils.js'), 'utf8');
  const grid = {
    classList: { remove() {} },
    innerHTML: '',
  };
  const context = {
    window: {
      AIFriendShared: {
        escapeHtml,
        sanitizeCssUrl: (url) => url,
        sanitizeCssColor: (color, fallback) => color || fallback,
      },
    },
    document: {
      getElementById(id) {
        if (id === 'char-grid') return grid;
        return null;
      },
    },
    CHARACTERS: characters,
    SERVER_ORIGIN: 'http://127.0.0.1:8000',
  };
  vm.createContext(context);
  vm.runInContext(code, context, { filename: 'frontend/modules/utils.js' });
  context.renderCharGrid();
  return grid.innerHTML;
}

(function runTests() {
  const maliciousTag = '<img src=x onerror="alert(1)">';
  const html = renderCharGridWithCharacters([
    {
      id: 'char_x',
      name: '测试角色',
      tags: [maliciousTag, 'safe&tag'],
      subtitle: '简介',
    },
  ]);

  assert.ok(!html.includes(maliciousTag), '角色标签不应保留原始 HTML');
  assert.ok(!html.includes('<img src=x'), '角色标签不应生成真实 img 元素');
  assert.ok(html.includes('&lt;img src=x onerror=&quot;alert(1)&quot;&gt;'));
  assert.ok(html.includes('safe&amp;tag'));

  const stringTagHtml = renderCharGridWithCharacters([
    {
      id: 'char_y',
      name: '字符串标签角色',
      tags: 'alpha, <script>alert(1)</script>, beta',
    },
  ]);
  assert.ok(stringTagHtml.includes('alpha'));
  assert.ok(!stringTagHtml.includes('<script>alert(1)</script>'));
  assert.ok(stringTagHtml.includes('&lt;script&gt;alert(1)&lt;/script&gt;'));

  let shared = loadSharedUtils();
  assert.strictEqual(shared.resolveApiBase(), 'http://127.0.0.1:8000/api');
  assert.strictEqual(shared.resolveApiBase({ admin: true }), 'http://127.0.0.1:8000/api/admin');

  shared = loadSharedUtils({ apiBase: '/mock-api' });
  assert.strictEqual(shared.resolveApiBase(), '/mock-api');
  assert.strictEqual(shared.resolveApiBase({ admin: true }), '/mock-api/admin');

  shared = loadSharedUtils({ apiBase: '/mock-api/', adminApiBase: '/mock-admin-api/' });
  assert.strictEqual(shared.resolveApiBase(), '/mock-api');
  assert.strictEqual(shared.resolveApiBase({ admin: true }), '/mock-admin-api');

  shared = loadSharedUtils({ metaApiBase: 'http://localhost:9999/api/' });
  assert.strictEqual(shared.resolveApiBase(), 'http://localhost:9999/api');

  console.log('✅ 前端安全回归测试通过');
})();
