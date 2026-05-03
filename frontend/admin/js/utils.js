/**
 * utils.js - 全局工具函数
 * 
 * 所有模块共享的通用工具：toast 提示、HTML 转义、日期格式化、
 * 标签处理、分页器渲染、CSV 下载等。
 */

/**
 * 显示底部 Toast 提示
 * @param {string} msg - 提示文案
 * @param {number} duration - 显示时长（毫秒），默认 2500
 */
function toast(msg, duration = 2500) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), duration);
}

/**
 * HTML 特殊字符转义，防止 XSS
 * 委托给共享的 window.AIFriendShared.escapeHtml，确保前后端行为一致
 * @param {*} s - 任意值，会被转为字符串处理
 * @returns {string} 转义后的安全 HTML 字符串
 */
function escHtml(s) {
  return window.AIFriendShared.escapeHtml(s);
}

/**
 * ISO 日期字符串格式化为 YYYY-MM-DD
 * @param {string} iso - ISO 格式日期
 * @returns {string}
 */
function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

/**
 * 会员档位名称映射
 * @param {string} plan - 档位标识
 * @returns {string} 中文显示名
 */
function formatPlanLabel(plan) {
  return ({ guest: '游客', free: '注册用户', vip: 'VIP', svip: 'SVIP' }[plan] || plan || '未知');
}

/**
 * 关系阶段中文名映射
 * @param {string} phase - 阶段标识
 * @returns {string}
 */
function getPhaseLabel(phase) {
  const labels = { stranger: '陌生人', acquaintance: '熟人', friend: '朋友', lover: '恋人' };
  return labels[phase] || phase;
}

/**
 * 将标签数据转为表单值（逗号分隔字符串）
 * 支持数组 ['a','b'] 和字符串 "a, b" 两种输入
 */
function tagsToFormValue(tags) {
  if (tags == null) return '';
  if (Array.isArray(tags)) return tags.join(', ');
  return String(tags);
}

/**
 * 将表单标签字符串转为后端需要的 JSON 数组格式
 * 如果已经是 JSON 数组则原样返回
 */
function formTagsToServer(s) {
  const t = (s || '').trim();
  if (!t) return '[]';
  if (t.startsWith('[')) {
    try {
      JSON.parse(t);
      return t;
    } catch (e) { /* 按逗号解析 */ }
  }
  return JSON.stringify(t.split(',').map(x => x.trim()).filter(Boolean));
}

/**
 * 校验 JSON 字符串合法性，不合法则抛错
 * @param {string} s - JSON 字符串
 * @param {string} label - 字段名称（用于报错提示）
 * @returns {string} 原始 JSON 字符串
 */
function validateJsonString(s, label) {
  const t = (s || '').trim();
  if (!t) return '{}';
  try {
    JSON.parse(t);
    return t;
  } catch (e) {
    throw new Error(label + ' 须为合法 JSON');
  }
}

/**
 * 渲染分页器到指定容器
 * @param {HTMLElement} container - 分页器容器
 * @param {number} page - 当前页码
 * @param {number} totalPages - 总页数
 * @param {number} total - 总条数
 * @param {Function} onPageChange - 页码变更回调，参数为新的页码
 */
function renderPager(container, page, totalPages, total, onPageChange) {
  if (!container) return;
  const pages = [];
  for (let i = 1; i <= Math.min(totalPages, 7); i++) pages.push(i);
  if (!container.dataset.pagerBound) {
    container.addEventListener('click', (event) => {
      const btn = event.target.closest('.pager-btn[data-page]');
      if (!btn || btn.disabled) return;
      event.preventDefault();
      const nextPage = parseInt(btn.dataset.page, 10);
      if (Number.isNaN(nextPage)) return;
      onPageChange(nextPage);
    });
    container.dataset.pagerBound = '1';
  }

  const makeBtn = (label, targetPage, disabled, active = false) => {
    const safeTarget = Math.min(totalPages, Math.max(1, targetPage));
    return `<button class="pager-btn ${active ? 'active' : ''}" data-page="${safeTarget}" ${disabled ? 'disabled' : ''}>${label}</button>`;
  };

  container.innerHTML = `
    <div class="pager-info">第 ${page} / ${totalPages} 页，共 ${total} 条</div>
    <div class="pager-controls">
      ${makeBtn('«', 1, page === 1)}
      ${makeBtn('‹', page - 1, page === 1)}
      ${pages.map(p => makeBtn(String(p), p, false, p === page)).join('')}
      ${makeBtn('›', page + 1, page >= totalPages)}
      ${makeBtn('»', totalPages, page >= totalPages)}
    </div>`;
}

/**
 * 生成并下载 CSV 文件
 * @param {string} filename - 文件名
 * @param {Array<string[]>} rows - 二维数组，第一行为表头
 */
function downloadCSV(filename, rows) {
  const csv = rows.map(r => r.map(v => `"${String(v || '').replace(/"/g, '""')}"`).join(',')).join('\n');
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * 逗号分隔的 ID 字符串拆分为数组
 * @param {string} raw - 如 "1,2,3"
 * @returns {string[]}
 */
function splitCsvIds(raw) {
  return String(raw || '')
    .split(',')
    .map(x => x.trim())
    .filter(Boolean);
}

/**
 * 获取选择器中所有选中的 checkbox 值
 * @param {string} selectorId - 容器的 DOM id
 * @returns {string[]}
 */
function getCheckedValues(selectorId) {
  return Array.from(document.querySelectorAll(`#${selectorId} input[type="checkbox"]:checked`)).map(el => el.value);
}

/**
 * 防抖函数：在指定延迟时间内只执行最后一次调用
 * @param {Function} fn - 要防抖的函数
 * @param {number} delay - 延迟毫秒数，默认 400
 * @returns {Function} 防抖包装后的函数
 */
function debounce(fn, delay = 400) {
  let timer = null;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}
