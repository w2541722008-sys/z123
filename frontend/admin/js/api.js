/**
 * api.js - API 封装 + 认证管理
 * 
 * 提供统一的 API 请求方法、token 管理、权限检查。
 * 所有模块都通过 AdminAPI.apiFetch() 发起请求。
 */
const AdminAPI = (() => {
  const shared = window.AIFriendShared;
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

  // localStorage key
  const TOKEN_KEY = shared?.STORAGE_KEYS?.TOKEN_KEY || 'aifriend_token';
  const USER_KEY = shared?.STORAGE_KEYS?.USER_KEY || 'aifriend_user';

  // 管理员权限是否已通过验证
  let _bootstrapped = false;
  // 当前登录的管理员用户信息
  let _currentUser = null;

  /**
   * 统一的 API 请求方法
   * 自动携带 Authorization token，统一处理错误
   * @param {string} url - 请求地址（可以是完整URL或相对路径）
   * @param {object} opts - fetch 选项，可选
   * @returns {Promise<any>} JSON 响应数据
   */
  async function apiFetch(url, opts = {}) {
    const token = localStorage.getItem(TOKEN_KEY) || '';
    const headers = {
      'Content-Type': 'application/json',
      ...(opts.headers || {}),
    };
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    const res = await fetch(url, { ...opts, headers });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      if (res.status === 401) {
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
          </div>
          <div style="margin-top:16px;font-size:12px;line-height:1.7;color:#888;">如果你本来就是管理员，请先在前台登录已授权邮箱，然后再回来打开这个页面。</div>
        </div>
      </div>
    `;
  }

  /**
   * 启动时检查管理员权限
   * 检测 token → 请求 /auth/me → 验证 is_admin
   * @returns {Promise<boolean>} 是否通过权限检查
   */
  async function bootstrapAdminPage() {
    if (_bootstrapped) return true;
    const token = localStorage.getItem(TOKEN_KEY) || '';
    console.log('[Admin Debug] TOKEN_KEY=', TOKEN_KEY, 'token=', token ? token.substring(0, 20) + '...' : '(empty)');
    if (!token) {
      renderAccessDenied('还没检测到登录令牌（localStorage 中无 aifriend_token）。请先在前台 http://lunawhisp.com 登录管理员账号，再刷新本页面。');
      return false;
    }
    try {
      const me = await apiFetch(`${_baseUrl}/auth/me`);
      console.log('[Admin Debug] /auth/me response:', JSON.stringify(me));
      _currentUser = me || null;
      localStorage.setItem(USER_KEY, JSON.stringify(me || null));
      if (!me?.is_admin) {
        renderAccessDenied('当前账号已登录，但 is_admin=false。邮箱: ' + (me?.email || '未知') + ', 请检查 .env 的 ADMIN_EMAILS 是否包含此邮箱。');
        return false;
      }
      _bootstrapped = true;
      return true;
    } catch (e) {
      console.error('[Admin Error]', e);
      renderAccessDenied('请求失败: ' + (e.message || e.toString()) + '。API地址: ' + _baseUrl + '/auth/me');
      return false;
    }
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
