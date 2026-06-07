/**
 * CSP onclick 合规检查
 *
 * 主应用启用严格 CSP（script-src 'self'），禁止任何 onclick 属性。
 * 本脚本扫描 frontend/modules/ 下所有 JS 文件，检查 innerHTML 或字符串模板中
 * 是否包含 onclick=，防止动态生成的 inline event handler 被浏览器 CSP 拦截。
 *
 * 用法：node tests/check_csp_onclick.js
 * 退出码：0 = 合规，1 = 发现违规
 */

const fs = require('fs');
const path = require('path');

const MODULES_DIR = path.join(__dirname, '..', 'frontend', 'modules');
const EXCLUDE = ['csp-bindings.js']; // 本文件只做绑定，允许在注释/字符串中提及 onclick

function scanDir(dir) {
  const violations = [];
  for (const entry of fs.readdirSync(dir)) {
    const fullPath = path.join(dir, entry);
    if (fs.statSync(fullPath).isDirectory()) continue;
    if (!entry.endsWith('.js')) continue;
    if (EXCLUDE.includes(entry)) continue;

    const content = fs.readFileSync(fullPath, 'utf-8');
    const lines = content.split('\n');
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      // 跳过注释行
      if (line.trim().startsWith('//') || line.trim().startsWith('*')) continue;
      // 检查 HTML 属性 onclick= （innerHTML/模板字符串中的 inline handler）
      // 排除 DOM 属性赋值：el.onclick = fn（合法，不受 CSP 影响）
      const hasHtmlOnclick = /\bonclick="|\bonclick='|onclick=\$/.test(line) && !/\.onclick\s*=/.test(line);
      if (hasHtmlOnclick) {
        violations.push({ file: entry, line: i + 1, text: line.trim().slice(0, 120) });
      }
    }
  }
  return violations;
}

const violations = scanDir(MODULES_DIR);

if (violations.length > 0) {
  console.log(`❌ CSP onclick 检查：发现 ${violations.length} 处违规`);
  console.log('   严格 CSP（script-src \'self\'）下，innerHTML 中的 onclick 会被浏览器拦截');
  violations.forEach(v => {
    console.log(`   ${v.file}:${v.line}  ${v.text}`);
  });
  process.exit(1);
} else {
  console.log('✅ CSP onclick 检查通过：frontend/modules/ 中无违规 onclick');
  process.exit(0);
}
