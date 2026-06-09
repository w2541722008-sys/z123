#!/usr/bin/env node
/**
 * 前端冒烟测试 - 快速发现运行时错误
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const PROJECT_DIR = path.join(__dirname, '..', '..');
const FRONTEND_DIR = path.join(PROJECT_DIR, 'frontend');
const ADMIN_DIR = path.join(FRONTEND_DIR, 'admin');

let errors = [];

// 1. 语法检查
console.log('🔍 检查 JS 语法...');
function checkSyntax(dir) {
  if (!fs.existsSync(dir)) return;
  const files = fs.readdirSync(dir, { withFileTypes: true });
  for (const file of files) {
    const fullPath = path.join(dir, file.name);
    if (file.isDirectory()) {
      checkSyntax(fullPath);
    } else if (file.name.endsWith('.js')) {
      try {
        execSync(`node --check "${fullPath}"`, { stdio: 'pipe' });
      } catch (e) {
        errors.push(`❌ 语法错误: ${fullPath.replace(PROJECT_DIR, '')}`);
      }
    }
  }
}
checkSyntax(path.join(FRONTEND_DIR, 'modules'));
checkSyntax(path.join(ADMIN_DIR, 'js'));

// 2. 检查关键函数定义
console.log('🔍 检查关键函数定义...');
const REQUIRED_GLOBALS = {
  'frontend/modules/utils.js': ['escapeHtml', 'formatTime'],
  'frontend/modules/api.js': ['API'],
  'frontend/admin/js/utils.js': ['escHtml'],
  'frontend/admin/js/char-editor.js': ['safeParseJSON', 'renderEditPanel'],
};

for (const [file, funcs] of Object.entries(REQUIRED_GLOBALS)) {
  const fullPath = path.join(PROJECT_DIR, file);
  if (!fs.existsSync(fullPath)) {
    errors.push(`❌ 文件不存在: ${file}`);
    continue;
  }
  const content = fs.readFileSync(fullPath, 'utf8');
  for (const func of funcs) {
    const patterns = [
      new RegExp(`function\\s+${func}\\s*\\(`),
      new RegExp(`const\\s+${func}\\s*=`),
      new RegExp(`${func}\\s*:\\s*function`),
    ];
    if (!patterns.some(p => p.test(content))) {
      errors.push(`❌ 函数未定义: ${func} in ${file}`);
    }
  }
}

// 3. 检查 admin data-action 完整性
console.log('🔍 检查 admin data-action...');
const adminIndexPath = path.join(ADMIN_DIR, 'index.html');
const actionsJsPath = path.join(ADMIN_DIR, 'js/actions.js');
if (fs.existsSync(adminIndexPath) && fs.existsSync(actionsJsPath)) {
  const adminIndexHtml = fs.readFileSync(adminIndexPath, 'utf8');
  const actionsJs = fs.readFileSync(actionsJsPath, 'utf8');
  const htmlActions = [...adminIndexHtml.matchAll(/data-action="([^"]+)"/g)].map(m => m[1]);
  const jsActions = [...actionsJs.matchAll(/'([a-z0-9-]+)'\s*:/g)].map(m => m[1]);
  for (const action of htmlActions) {
    if (!jsActions.includes(action)) {
      errors.push(`❌ data-action 无 handler: ${action}`);
    }
  }
}

// 4. 检查 admin 登录启动逻辑
console.log('🔍 检查 admin 登录启动逻辑...');
const adminApiPath = path.join(ADMIN_DIR, 'js/api.js');
if (fs.existsSync(adminApiPath)) {
  const adminApiJs = fs.readFileSync(adminApiPath, 'utf8');
  if (adminApiJs.includes('localStorage 中无 aifriend_token')) {
    errors.push('❌ admin 启动仍硬依赖 localStorage token，Cookie 登录会被误拦截');
  }
  if (!/credentials\s*:\s*['"]include['"]/.test(adminApiJs)) {
    errors.push('❌ AdminAPI.apiFetch 未默认携带 credentials: include');
  }
  if (/if\s*\(\s*!token\s*\)/.test(adminApiJs)) {
    errors.push('❌ admin bootstrap 仍在请求 /auth/me 前直接拦截空 token');
  }
  if (/Authorization\s*=|headers\.Authorization|Bearer\s+\$\{token\}|localStorage\.setItem\(\s*TOKEN_KEY/.test(adminApiJs)) {
    errors.push('❌ AdminAPI 仍在读写 JS token 或发送 Authorization fallback');
  }
}

// 5. 检查前台认证不暴露/存储 token
console.log('🔍 检查前台 token 存储治理...');
const frontendApiPath = path.join(FRONTEND_DIR, 'modules', 'api.js');
const frontendAuthPath = path.join(FRONTEND_DIR, 'modules', 'auth.js');
const frontendConfigPath = path.join(FRONTEND_DIR, 'modules', 'config.js');
for (const filePath of [frontendApiPath, frontendAuthPath, frontendConfigPath]) {
  if (!fs.existsSync(filePath)) continue;
  const content = fs.readFileSync(filePath, 'utf8');
  if (/sessionStorage\.setItem\(\s*['"]aifriend_token_refresh/.test(content)) {
    errors.push(`❌ refresh token 仍写入 sessionStorage: ${path.basename(filePath)}`);
  }
  if (/localStorage\.setItem\(\s*TOKEN_KEY|headers\.Authorization|Authorization\s*=|Bearer\s+\$\{token\}/.test(content)) {
    errors.push(`❌ access token 仍写入 localStorage 或作为 Authorization 发送: ${path.basename(filePath)}`);
  }
  if (/data\.access_token|result\.access_token|result\.refresh_token/.test(content)) {
    errors.push(`❌ 前端仍依赖响应体 token 字段: ${path.basename(filePath)}`);
  }
}

// 输出结果
console.log('\n' + '='.repeat(60));
if (errors.length === 0) {
  console.log('✅ 前端冒烟测试通过');
  process.exit(0);
} else {
  console.log(`❌ 发现 ${errors.length} 个问题:\n`);
  errors.forEach(e => console.log(e));
  process.exit(1);
}
