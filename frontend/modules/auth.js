 const Auth = (() => {
   let loggedIn = false;
   let user = null;
   let currentTab = 'login'; // 当前 Tab：'login' 或 'register'

   function openLogin() {
     // 每次打开弹窗，默认展示"登录"Tab
     switchTab('login');
     document.getElementById('login-modal').classList.add('open');
   }

   function closeLogin(e) {
     if (e && e.target !== document.getElementById('login-modal')) return;
     document.getElementById('login-modal').classList.remove('open');
   }

   /** 切换登录/注册 Tab */
   function switchTab(tab) {
     currentTab = tab;
     const subEl    = document.getElementById('auth-modal-sub');
     const nickEl   = document.getElementById('input-nickname');
     const submitEl = document.getElementById('auth-submit-btn');
     const loginTab = document.getElementById('tab-login');
     const regTab   = document.getElementById('tab-register');

     if (tab === 'login') {
       loginTab.classList.add('active');
       regTab.classList.remove('active');
       subEl.textContent    = '欢迎回来，登录后聊天记录持续保存。';
       nickEl.style.display = 'none';
       submitEl.textContent = '确认登录';
     } else {
       regTab.classList.add('active');
       loginTab.classList.remove('active');
       subEl.textContent    = '注册后会持续保存聊天记录和关键记忆，后续体验会更连贯。';
       nickEl.style.display = '';
       submitEl.textContent = '立即注册';
     }
   }

   /** Tab 提交分发：根据当前 Tab 调用登录或注册 */
   function doSubmit() {
     if (currentTab === 'login') {
       doLogin();
     } else {
       doRegister();
     }
   }

  /** 登录成功后的统一处理 */
  function _onAuthSuccess(result) {
    // Cookie 由浏览器自动管理，此处仅保留 token 作为过渡兼容
    // 后端已同时设置 HttpOnly Cookie，前端不再必须手动存储 token
    if (result.access_token) {
      AppState.setToken(result.access_token);
    }
    if (result.refresh_token) {
      AppState.setRefreshToken(result.refresh_token);
      try { sessionStorage.setItem('aifriend_token_refresh', result.refresh_token); } catch (_) {}
    }
    user = {
      id: result.user.id,
      name: result.user.nickname,
      email: result.user.email,
      avatar_url: result.user.avatar_url || '',
    };
    loggedIn = true;
    AppState.setUser(user);
    closeLogin();
    renderProfile();
     // 登录后隐藏游客体验额度提示
     if (typeof Chat !== 'undefined') Chat.renderGuestQuotaBar();
     // 保存游客聊天历史（登录后合并到用户账号）
     if (typeof Chat !== 'undefined' && Chat.currentChar && Chat.history) {
       var guestMsgs = Chat.history;
       var guestCid = Chat.currentChar.id;
       if (guestMsgs && guestMsgs.length && guestCid) {
         window.__guestChatHistory = guestMsgs.slice(-50);
         window.__guestChatCharId = guestCid;
       }
     }
     // 登录/注册成功后：有上次聊天角色则跳过去，否则跳角色广场
     setTimeout(() => {
       const lastId = AppState.getLastCharacterId();
       const lastChar = CHARACTERS.find(c => c.id === lastId);
       if (lastChar) {
         Chat.enterChat(lastChar);
       } else if (App.currentPage === 'mine') {
         App.nav('square');
       }
     }, 600);
   }

   async function doLogin() {
     const email    = document.getElementById('input-email').value.trim();
     const password = document.getElementById('input-password').value.trim();
     if (!email)    { UI.toast('请输入邮箱', 'warn'); return; }
     if (!password || password.length < 8) { UI.toast('密码至少 8 位', 'warn'); return; }

     try {
       const result = await API.login({ email, password });
       _onAuthSuccess(result);
       UI.toast('✓ 登录成功，聊天记录将持续保存', 'success');
     } catch (err) {
       // 如果后端提示"账号不存在"，引导用户切到注册 Tab
       if (err.message && err.message.includes('不存在')) {
         UI.toast('该邮箱未注册，请先注册 →', 'warn');
         setTimeout(() => switchTab('register'), 800);
       } else {
         UI.toast(`登录失败：${err.message}`, 'error');
       }
     }
   }

   async function doRegister() {
     const email    = document.getElementById('input-email').value.trim();
     const nickname = document.getElementById('input-nickname').value.trim();
     const password = document.getElementById('input-password').value.trim();
     if (!email)    { UI.toast('请输入邮箱', 'warn'); return; }
     if (!password || password.length < 8) { UI.toast('密码至少 8 位', 'warn'); return; }

     try {
       const result = await API.register({ email, password, nickname });
       _onAuthSuccess(result);
       UI.toast('✓ 注册成功！后续聊天记录会持续保存', 'success');
     } catch (err) {
       // 如果后端提示"已注册"，引导用户切到登录 Tab
       if (err.message && err.message.includes('已注册')) {
         UI.toast('该邮箱已注册，请直接登录 →', 'warn');
         setTimeout(() => switchTab('login'), 800);
       } else {
         UI.toast(`注册失败：${err.message}`, 'error');
       }
     }
   }

   async function bootstrap() {
     const cachedUser = AppState.getUser();
     if (cachedUser) {
       user = cachedUser;
       loggedIn = true;
       renderProfile();
     }

     // 尝试用 Cookie 认证（优先）或 Authorization 头（兼容）
     // 不再依赖 localStorage token 存在性判断登录状态
     try {
      const me = await API.me();
      user = { name: me.nickname, email: me.email, id: me.id, avatar_url: me.avatar_url || '' };
      loggedIn = true;
      AppState.setUser(user);
    } catch (err) {
      const msg = (err.message || '').toLowerCase();
      if (msg.includes('未认证') || msg.includes('未授权') || msg.includes('invalid') || msg.includes('expired') || msg.includes('401') || msg.includes('403')) {
        AppState.setToken('');
        AppState.setUser(null);
        loggedIn = false;
        user = null;
      }
    }
     renderProfile();
   }

   async function logout() {
     try {
       await API.logout();  // 后端会清除 Cookie
     } catch (e) { console.warn('logout 请求失败，前端仍会清除本地状态', e); }
     AppState.setToken('');
     AppState.setRefreshToken('');
    try { sessionStorage.removeItem('aifriend_token_refresh'); } catch (_) {}
     AppState.setUser(null);
     loggedIn = false;
     user = null;
     renderProfile();
     if (typeof Chat !== 'undefined') Chat.refreshGuestQuota();
   }

   function renderProfile() {
    const profileHeader = document.getElementById('profile-header');
    const loginBtn  = document.getElementById('login-btn');
    const logoutBtn = document.getElementById('logout-btn');
    if (loggedIn && user) {
      profileHeader.style.display = 'flex';
      const avatarEl = document.getElementById('profile-avatar-char');
      avatarEl.textContent = '';
      avatarEl.style.background = 'none';
      if (user.avatar_url) {
        const imgSrc = user.avatar_url.startsWith('/') ? SERVER_ORIGIN + user.avatar_url : user.avatar_url;
        const img = document.createElement('img');
        img.src = imgSrc;
        img.alt = user.name || '你';
        img.style.cssText = 'width:100%;height:100%;object-fit:cover;border-radius:inherit';
        img.onerror = () => { avatarEl.textContent = (user.name || '你')[0].toUpperCase(); avatarEl.style.background = ''; };
        avatarEl.appendChild(img);
        avatarEl.style.cursor = 'pointer';
        avatarEl.onclick = () => document.getElementById('avatar-file-input')?.click();
      } else {
        avatarEl.textContent = (user.name || user.email || '你')[0].toUpperCase();
        avatarEl.style.background = '';
        avatarEl.onclick = () => document.getElementById('avatar-file-input')?.click();
      }
      document.getElementById('profile-name').textContent = user.name || user.email;
      document.getElementById('profile-email').textContent = user.email;
      loginBtn.style.display  = 'none';
      logoutBtn.style.display = '';
    } else {
      profileHeader.style.display = 'none';
      loginBtn.style.display  = '';
      logoutBtn.style.display = 'none';
    }
  }

  async function uploadAvatar(file) {
    try {
      const result = await API.uploadAvatar(file);
      if (user) {
        user.avatar_url = result.avatar_url;
        AppState.setUser(user);
      }
      renderProfile();
      UI.toast('✓ 头像更新成功', 'success');
    } catch (err) {
      UI.toast(`头像上传失败：${err.message}`, 'error');
    }
  }

  function getUser() {
    return user;
  }

  function isLoggedIn() {
    return loggedIn;
  }

  return { openLogin, closeLogin, switchTab, doSubmit, doLogin, doRegister, logout, bootstrap, isLoggedIn, getUser, uploadAvatar, renderProfile };
})();
