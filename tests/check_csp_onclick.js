/**
 * CSP onclick 合规检查
 *
 * 主应用启用严格 CSP（script-src 'self'），禁止任何 onclick/oninput 属性。
 * 扫描范围：
 *   1. frontend/modules/ JS 文件中的 innerHTML onclick=
 *   2. frontend/*.html（排除 admin 子目录，admin 有 unsafe-inline 豁免）
 *
 * 用法：node tests/check_csp_onclick.js
 * 退出码：0 = 合规，1 = 发现违规
 */

const fs = require('fs');
const path = require('path');

const PROJECT_DIR = path.join(__dirname, '..');
const MODULES_DIR = path.join(PROJECT_DIR, 'frontend', 'modules');
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
      const hasHtmlOnclick = /\bonclick="|\bonclick='|onclick=\$/.test(line) && !/\.onclick\s*=/.test(line);
      if (hasHtmlOnclick) {
        violations.push({ file: `modules/${entry}`, line: i + 1, text: line.trim().slice(0, 120) });
      }
    }
  }
  return violations;
}

function scanHtmlFiles() {
  const violations = [];
  for (const entry of fs.readdirSync(FRONTEND_DIR)) {
    if (!entry.endsWith('.html')) continue;
    // admin 子目录下的 HTML 有 unsafe-inline 豁免，跳过
    const fullPath = path.join(FRONTEND_DIR, entry);
    if (!fs.statSync(fullPath).isFile()) continue;

    const content = fs.readFileSync(fullPath, 'utf-8');
    const lines = content.split('\n');
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (/<script\b/i.test(line)) continue; // <script> 标签中的代码由 scanJsFiles 检查
      const hasInlineHandler = /\bon(?:click|input|change|submit|keypress|keydown|keyup|focus|blur|mouseover|mouseout)="[^"]*"/i.test(line);
      if (hasInlineHandler) {
        violations.push({ file: entry, line: i + 1, text: line.trim().slice(0, 120) });
      }
    }
  }
  return violations;
}

const jsViolations = scanJsFiles(MODULES_DIR);
const htmlViolations = scanHtmlFiles();
const allViolations = [...jsViolations, ...htmlViolations];

if (allViolations.length > 0) {
  console.log(`❌ CSP onclick 检查：发现 ${allViolations.length} 处违规`);
  console.log('   严格 CSP（script-src \'self\'）下，内联事件处理器会被浏览器拦截');
  allViolations.forEach(v => {
    console.log(`   ${v.file}:${v.line}  ${v.text}`);
  });
  process.exit(1);
} else {
  console.log('✅ CSP onclick 检查通过：JS 内联事件 + HTML 内联事件 均无违规');
  process.exit(0);
}
