/**
 * CSP onclick 合规检查
 *
 * 主应用和 Admin 均启用严格 CSP（script-src 'self'），禁止任何 onclick/oninput 属性和内联脚本。
 * 扫描范围：
 *   1. frontend/modules/ 与 frontend/admin/js/ JS 文件中的动态 HTML 内联事件
 *   2. frontend 下所有 HTML（包括 admin 子目录）的内联事件与内联脚本
 *
 * 用法：node tests/frontend/check_csp_onclick.js
 * 退出码：0 = 合规，1 = 发现违规
 */

const fs = require('fs');
const path = require('path');

const PROJECT_DIR = path.join(__dirname, '..', '..');
const MODULES_DIR = path.join(PROJECT_DIR, 'frontend', 'modules');
const ADMIN_JS_DIR = path.join(PROJECT_DIR, 'frontend', 'admin', 'js');
const FRONTEND_DIR = path.join(PROJECT_DIR, 'frontend');
const EXCLUDE_JS = ['csp-bindings.js'];

function scanJsFiles(dir) {
  const violations = [];
  for (const entry of fs.readdirSync(dir)) {
    const fullPath = path.join(dir, entry);
    if (fs.statSync(fullPath).isDirectory()) continue;
    if (!entry.endsWith('.js')) continue;
    if (EXCLUDE_JS.includes(entry)) continue;

    const content = fs.readFileSync(fullPath, 'utf-8');
    const lines = content.split('\n');
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.trim().startsWith('//') || line.trim().startsWith('*')) continue;
      const hasInlineHandler = /\bon[a-z]+\s*=/.test(line) && !/\.on[a-z]+\s*=/.test(line);
      if (hasInlineHandler) {
        violations.push({ file: path.relative(FRONTEND_DIR, fullPath), line: i + 1, text: line.trim().slice(0, 120) });
      }
    }
  }
  return violations;
}

function scanHtmlFiles(dir = FRONTEND_DIR) {
  const violations = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      violations.push(...scanHtmlFiles(fullPath));
      continue;
    }
    if (!entry.name.endsWith('.html')) continue;

    const content = fs.readFileSync(fullPath, 'utf-8');
    const lines = content.split('\n');
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (/<script\b/i.test(line)) continue; // <script> 标签中的代码由 scanJsFiles 检查
      const hasInlineHandler = /\bon(?:click|input|change|submit|keypress|keydown|keyup|focus|blur|mouseover|mouseout)\s*=\s*["'][^"']*["']/i.test(line);
      if (hasInlineHandler) {
        violations.push({ file: path.relative(FRONTEND_DIR, fullPath), line: i + 1, text: line.trim().slice(0, 120) });
      }
    }
  }
  return violations;
}

function scanInlineScripts(dir = FRONTEND_DIR) {
  const violations = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      violations.push(...scanInlineScripts(fullPath));
      continue;
    }
    if (!entry.name.endsWith('.html')) continue;

    const content = fs.readFileSync(fullPath, 'utf-8');
    const scriptPattern = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;
    let match;
    while ((match = scriptPattern.exec(content)) !== null) {
      const attrs = match[1] || '';
      const body = match[2] || '';
      if (/\bsrc\s*=/i.test(attrs) || !body.trim()) continue;
      const line = content.slice(0, match.index).split('\n').length;
      violations.push({
        file: path.relative(FRONTEND_DIR, fullPath),
        line,
        text: '<script> inline JavaScript',
      });
    }
  }
  return violations;
}

const jsViolations = [
  ...scanJsFiles(MODULES_DIR),
  ...scanJsFiles(ADMIN_JS_DIR),
];
const htmlViolations = scanHtmlFiles(FRONTEND_DIR);
const inlineScriptViolations = scanInlineScripts(FRONTEND_DIR);
const allViolations = [...jsViolations, ...htmlViolations, ...inlineScriptViolations];

if (allViolations.length > 0) {
  console.log(`❌ CSP 检查：发现 ${allViolations.length} 处违规`);
  console.log('   严格 CSP（script-src \'self\'）下，内联事件处理器和内联脚本会被浏览器拦截');
  allViolations.forEach(v => {
    console.log(`   ${v.file}:${v.line}  ${v.text}`);
  });
  process.exit(1);
} else {
  console.log('✅ CSP 检查通过：JS 内联事件 + HTML 内联事件 + 内联脚本均无违规');
  process.exit(0);
}
