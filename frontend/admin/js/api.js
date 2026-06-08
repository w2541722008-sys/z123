/**
 * api.js - API 封装 + 认证管理
 * 
 * 提供统一的 API 请求方法、token 管理、权限检查。
 * 所有模块都通过 AdminAPI.apiFetch() 发起请求。
 */
const AdminAPI = (() => {
  const shared = window.AIFriendShared;
  const REQUEST_TIMEOUT_MS = 20000;
  // API 地址动态适配（本地开发 vs ngrok/生产）
  const _apiBase = (() => {
    if (shared && typeof shared.resolveApiBase === 'function') {
      return shared.resolveApiBase({ admin: true });
    }
    const { protocol, hostname, port } = location;
    if (port === '8000' || port === '' || port === '443' || port === '80') {
      return `${protocol}//${hostname}${port ? ':' + port : ''}/api/admin`;
    }
    return `${protocol}//${hostname}:8000/api/admin`;
  })();
  // 不带 /admin 后缀的基础地址（用于 /auth/me 等非 admin 接口）
  const _baseUrl = _apiBase.replace(/\/admin$/, '');

  // Cookie 刷新（与前台 api.js 保持一致的 dedup promise 模式）
  let _refreshPromise = null;

  async function _tryRefresh() {
    if (_refreshPromise) return _refreshPromise;
    _refreshPromise = (async () => {
      try {
        // 不发送 Authorization header，完全依赖 HttpOnly Refresh Cookie（aifriend_refresh）。
        // 原因：Authorization header 中若携带旧 token，后端会优先读取并验证设备指纹，
        // IP 变化后指纹不匹配导致刷新失败。HttpOnly Cookie 由浏览器自动管理，更可靠。
        const resp = await fetch(`${_baseUrl}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
        });
        return resp.ok;
      } catch (_) {
        return false;
      } finally {
        _refreshPromise = null;
      }
    })();
    return _refreshPromise;
  }

  // localStorage key（TOKEN_KEY 仅用于清理旧版本残留 token）
  const TOKEN_KEY = shared?.STORAGE_KEYS?.TOKEN_KEY || 'aifriend_token';
  const USER_KEY = shared?.STORAGE_KEYS?.USER_KEY || 'aifriend_user';

  // 管理员权限是否已通过验证
  let _bootstrapped = false;
  // 当前登录的管理员用户信息
  let _currentUser = null;

  /**
   * 统一的 API 请求方法
   * 统一处理错误，认证完全依赖 HttpOnly Cookie。
   * @param {string} url - 请求地址（可以是完整URL或相对路径）
   * @param {object} opts - fetch 选项，可选
   * @returns {Promise<any>} JSON 响应数据
   */
  async function apiFetch(url, opts = {}) {
    const controller = new AbortController();
    const timeoutMs = opts.timeout || REQUEST_TIMEOUT_MS;
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const headers = {
      'Content-Type': 'application/json',
      ...(opts.headers || {}),
    };
    let res;
    try {
      res = await fetch(url, { credentials: 'include', ...opts, headers, signal: opts.signal || controller.signal });
    } catch (err) {
      if (err.name === 'AbortError') {
        throw new Error('请求超时，请检查网络后重试');
      }
      throw new Error('网络请求失败，请稍后重试');
    } finally {
      clearTimeout(timer);
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      if (res.status === 401 && !opts._retried) {
        const refreshed = await _tryRefresh();
        if (refreshed) {
          return apiFetch(url, { ...opts, _retried: true });
        }
        throw new Error('请先登录普通前台账号，再进入管理后台');
      }
      if (res.status === 403) {
        throw new Error(err.detail || '你没有管理后台权限');
      }
      throw new Error(err.detail || res.statusText);
    }
    return res.json();
  }

  /**
   * 渲染"无权限"拦截页面，替换整个 body 内容
   * @param {string} message - 提示文案
   */
  function renderAccessDenied(message) {
    document.body.innerHTML = `
      <div style="min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0f0f13;padding:24px;">
        <div style="max-width:560px;width:100%;background:#1a1a24;border:1px solid #2a2a3a;border-radius:18px;padding:28px;color:#e8e8f0;box-shadow:0 12px 40px rgba(0,0,0,.35);">
          <div style="font-size:28px;margin-bottom:12px;">🔐</div>
          <h1 style="font-size:22px;margin-bottom:10px;">管理后台已拦截</h1>
          <p style="font-size:14px;line-height:1.8;color:#b6bac7;margin-bottom:18px;">${escHtml(message || '你暂时没有管理后台权限。')}</p>
          <div style="display:flex;gap:10px;flex-wrap:wrap;">
            <a href="/" style="display:inline-flex;align-items:center;justify-content:center;padding:10px 16px;border-radius:10px;background:#7c3aed;color:#fff;text-decoration:none;font-size:14px;font-weight:600;">返回前台首页</a>
            <button data-action="admin-reload" style="padding:10px 16px;border-radius:10px;border:1px solid #3a3a4a;background:#2a2a3a;color:#e8e8f0;font-size:14px;cursor:pointer;">重新检查权限</button>
            <button data-action="admin-clear-relogin" style="padding:10px 16px;border-radius:10px;border:1px solid #dc2626;background:transparent;color:#fca5a5;font-size:14px;cursor:pointer;">清除登录状态并重新登录</button>
          </div>
          <div style="margin-top:16px;font-size:12px;line-height:1.7;color:#888;">如果你本来就是管理员，请先在前台登录已授权邮箱，然后再回来打开这个页面。</div>
        </div>
      </div>
    `;
  }

  /**
   * 启动时检查管理员权限
   * 请求 /auth/me → 验证 is_admin
   * @returns {Promise<boolean>} 是否通过权限检查
   */
  async function bootstrapAdminPage() {
    if (_bootstrapped) return true;

    // 多次重试 + 指数退避（处理网络延迟、Cookie 时序、token 刷新竞态等）
    const retryDelays = [0, 500, 1500];
    let lastError = null;

    for (let i = 0; i < retryDelays.length; i++) {
      if (i > 0) await new Promise(r => setTimeout(r, retryDelays[i]));
      try {
        const me = await apiFetch(`${_baseUrl}/auth/me`);
        _currentUser = me || null;
        localStorage.setItem(USER_KEY, JSON.stringify(me || null));
        if (!me?.is_admin) {
          renderAccessDenied('当前账号已登录，但 is_admin=false。邮箱: ' + (me?.email || '未知') + ', 请检查 .env 的 ADMIN_EMAILS 是否包含此邮箱。');
          return false;
        }
        _bootstrapped = true;
        return true;
      } catch (e) {
        lastError = e;
        console.warn(`[Admin] 第 ${i + 1} 次鉴权失败:`, e.message);
      }
    }

    console.error('[Admin] 所有鉴权重试失败');
    renderAccessDenied('请求失败: ' + (lastError?.message || '鉴权超时') + '。API地址: ' + _baseUrl + '/auth/me');
    return false;
  }

  // 导出公开接口
  return {
    API: _apiBase,           // /api/admin 地址
    API_BASE: _baseUrl,       // /api 地址
    TOKEN_KEY,
    USER_KEY,
    get currentUser() { return _currentUser; },
    get bootstrapped() { return _bootstrapped; },
    apiFetch,
    renderAccessDenied,
    bootstrapAdminPage,
  };
})();
