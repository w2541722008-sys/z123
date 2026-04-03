/* ================================================================
   数据层：底部导航配置
================================================================ */
 const NAV_CONFIG = [
   { id: 'home',   icon: '⌂',  label: '首页'  },
   { id: 'square', icon: '♡',  label: '角色'  },
   { id: 'chat',   icon: '✦',  label: '聊天'  },
   { id: 'mine',   icon: '☻',  label: '我的'  },
   // 扩展位：{ id: 'explore', icon: '⊕', label: '发现' }
 ];

 /* ================================================================
    数据层：角色卡配置
    当前改为由后端接口动态拉取，前端保留数组作为运行时状态容器。
    ================================================================ */
 // API_BASE 动态适配：
 //   - 本地开发（通过 npx serve 访问 3030 端口）→ 后端在 8000
 //   - 通过后端直接访问（ngrok / 生产）→ 同源，不加端口
 const API_BASE = (() => {
   const { protocol, hostname, port } = location;
   // 如果当前页面就是从后端 8000 端口（或 ngrok/生产域名）打开的，直接用同源
   if (port === '8000' || port === '' || port === '443' || port === '80') {
     return `${protocol}//${hostname}${port ? ':' + port : ''}/api`;
   }
   // 本地开发：页面在 3030，后端在 8000
   return `${protocol}//${hostname}:8000/api`;
 })();
 let CHARACTERS = [];


 /* 当前版本已切到后端统一调用，前端不再直接请求第三方模型。 */

 const AppState = (() => {
   const TOKEN_KEY = 'aifriend_token';
   const USER_KEY = 'aifriend_user';
   const LAST_CHAR_KEY = 'aifriend_last_char';

   function setToken(token) {
     if (token) {
       localStorage.setItem(TOKEN_KEY, token);
     } else {
       localStorage.removeItem(TOKEN_KEY);
     }
   }

   function getToken() {
     return localStorage.getItem(TOKEN_KEY) || '';
   }

   function setUser(user) {
     if (user) {
       localStorage.setItem(USER_KEY, JSON.stringify(user));
     } else {
       localStorage.removeItem(USER_KEY);
     }
   }

   function getUser() {
     try {
       return JSON.parse(localStorage.getItem(USER_KEY) || 'null');
     } catch (_) {
       return null;
     }
   }

   function setLastCharacterId(characterId) {
     if (characterId) {
       localStorage.setItem(LAST_CHAR_KEY, characterId);
     } else {
       localStorage.removeItem(LAST_CHAR_KEY);
     }
   }

   function getLastCharacterId() {
     return localStorage.getItem(LAST_CHAR_KEY) || '';
   }

   return {
     setToken,
     getToken,
     setUser,
     getUser,
     setLastCharacterId,
     getLastCharacterId,
   };
 })();

 function fallbackRequireLogin() {
   UI.toast('请先登录，再使用这个功能。', 'warn');
   Auth.openLogin();
 }

 function normalizeCharacterCardPayload(char = {}) {
   const avatarImg = char.avatarImg || char.avatar_url || '';
   const coverImg = char.coverImg || char.cover_url || '';
   const openingMessage = char.opening_message || char.first_message || char.first_mes || '';
   return {
     ...char,
     avatarImg,
     coverImg,
     avatar_url: avatarImg || char.avatar_url || '',
     cover_url: coverImg || char.cover_url || '',
     opening_message: openingMessage,
     first_message: char.first_message || char.first_mes || openingMessage,
   };
 }

 function safeApiCall(action) {
   if (!Auth.isLoggedIn()) {
     fallbackRequireLogin();
     return Promise.reject(new Error('未登录'));
   }
   return action();
 }

 /* ================================================================
    API 模块：统一走本地 FastAPI 后端
 ================================================================ */
