/**
 * 前端共享工具库 - 在所有页面（主站、管理后台、找回密码）最先加载
 *
 * 暴露到 window.AIFriendShared，供 modules/ 和 admin/ 引用：
 *   - resolveApiBase: API 地址动态适配
 *   - escapeHtml: XSS 防护的 HTML 转义
 *   - sanitizeCssUrl: CSS 注入防护的 URL 转义
 *   - STORAGE_KEYS: localStorage 键名常量
 */
(() => {
  function normalizeApiBase(value) {
    return String(value || '').trim().replace(/\/+$/, '');
  }

  function readMetaContent(name) {
    if (typeof document === 'undefined' || typeof document.querySelector !== 'function') {
      return '';
    }
    const meta = document.querySelector(`meta[name="${name}"]`);
    return meta ? normalizeApiBase(meta.content) : '';
  }

  function readConfiguredApiBase({ admin = false } = {}) {
    const adminOverride = normalizeApiBase(window.__ADMIN_API_BASE__) || readMetaContent('aifriend-admin-api-base');
    const baseOverride = normalizeApiBase(window.__API_BASE__) || readMetaContent('aifriend-api-base');
    if (admin) {
      if (adminOverride) return adminOverride;
      if (baseOverride) return baseOverride.endsWith('/admin') ? baseOverride : `${baseOverride}/admin`;
      return '';
    }
    return baseOverride;
  }

  function resolveApiBase({ admin = false } = {}) {
    const configuredBase = readConfiguredApiBase({ admin });
    if (configuredBase) return configuredBase;

    const { protocol, hostname, port } = location;
    const isBackendOrigin = port === '8000' || port === '' || port === '443' || port === '80';
    if (isBackendOrigin) {
      const origin = `${protocol}//${hostname}${port ? ':' + port : ''}`;
      return admin ? `${origin}/api/admin` : `${origin}/api`;
    }
    if (admin) {
      return `${protocol}//${hostname}:8000/api/admin`;
    }
    return `${protocol}//${hostname}:8000/api`;
  }

  /**
   * 统一的 HTML 转义函数，防止 XSS。
   * @param {*} text - 任意值，会被转为字符串处理
   * @param {Object} [options] - 配置项
   * @param {boolean} [options.convertNewlines=false] - 是否将 \n 转为 <br/>
   * @returns {string} 转义后的安全 HTML 字符串
   */
  function escapeHtml(text = '', { convertNewlines = false } = {}) {
    let result = String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
    if (convertNewlines) {
      result = result.replace(/\n/g, '<br/>');
    }
    return result;
  }

  /**
   * CSS url() 值安全转义，防止 CSS 注入。
   * 只允许 http(s):// 和 / 开头的 URL，对反斜杠和引号进行 CSS 转义。
   * @param {string} url - 待转义的 URL
   * @returns {string} 安全的 URL（可直接放入 url('...') 中使用）
   */
  function sanitizeCssUrl(url) {
    if (!url || typeof url !== 'string') return '';
    // 只允许合法 URL 协议和相对路径
    if (!/^(https?:\/\/|\/)/i.test(url)) return '';
    // CSS 字符串内转义：反斜杠和单引号（url 使用单引号包裹）
    return url
      .replace(/\\/g, '\\\\')
      .replace(/'/g, "\\'");
  }

  /**
   * 校验 CSS 颜色值，仅允许安全的颜色格式。
   * 防止将用户输入的恶意字符串注入 style 属性。
   *
   * @param {string} color - 用户输入的颜色值
   * @param {string} fallback - 校验失败时的回退颜色
   * @returns {string} 安全的 CSS 颜色值
   */
  function sanitizeCssColor(color, fallback) {
    if (!color || typeof color !== 'string') return fallback || '#1a1b30';
    var trimmed = color.trim();
    // 允许：hex (#rgb, #rrggbb, #rrggbbaa)、rgb()、rgba()、hsl()、hsla()
    if (/^#[0-9a-fA-F]{3,8}$/.test(trimmed)) return trimmed;
    if (/^(rgb|rgba|hsl|hsla)\([^)]*\)$/i.test(trimmed)) return trimmed;
    return fallback || '#1a1b30';
  }

  window.AIFriendShared = {
    STORAGE_KEYS: {
      TOKEN_KEY: 'aifriend_token',
      USER_KEY: 'aifriend_user',
    },
    resolveApiBase,
    escapeHtml,
    sanitizeCssUrl,
    sanitizeCssColor,
  };
})();
