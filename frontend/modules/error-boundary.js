/**
 * 全局错误边界 — 捕获未处理的 JS 异常和 Promise 拒绝，防止白屏。
 *
 * 功能：
 *   - window.onerror：捕获运行时异常
 *   - unhandledrejection：捕获未处理的 Promise 异常
 *   - online/offline：网络状态变化提示
 *
 * 此模块必须在所有其他业务模块之前加载。
 */
(() => {
  // ── 全局 JS 异常捕获 ──
  window.addEventListener('error', (e) => {
    // 忽略资源加载错误（img/script/link），这些由各自模块处理
    if (e.target && e.target !== window) return;
    console.error('[全局错误]', (e.error || e.message || '未知错误'));
    if (typeof UI !== 'undefined' && UI.toast) {
      UI.toast('页面出了点问题，请刷新重试', 'error');
    }
  });

  // ── 未处理的 Promise 异常 ──
  window.addEventListener('unhandledrejection', (e) => {
    const reason = e.reason;
    // AbortError 是用户主动取消请求，不需要提示
    if (reason?.name === 'AbortError') return;
    console.error('[未处理的Promise异常]', (reason?.message || '未知异常'));
    if (typeof UI !== 'undefined' && UI.toast) {
      const msg = reason?.message || '操作失败，请稍后重试';
      UI.toast(msg, 'error');
    }
  });

  // ── 网络状态检测 ──
  window.addEventListener('offline', () => {
    if (typeof UI !== 'undefined' && UI.toast) {
      UI.toast('网络已断开，部分功能可能不可用', 'warn', 4000);
    }
  });

  window.addEventListener('online', () => {
    if (typeof UI !== 'undefined' && UI.toast) {
      UI.toast('网络已恢复', 'success');
    }
  });
})();
