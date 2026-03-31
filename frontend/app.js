   /* ================================================================
      UI 工具模块：Toast（轻提示）+ ConfirmModal（确认弹窗）
      用于替代原生 alert() / window.confirm()，保持沉浸式体验
   ================================================================ */
   const UI = (() => {
     let _toastTimer = null;

     /**
      * 显示一个轻量 Toast 提示，自动消失。
      * @param {string} msg    - 提示文字
      * @param {'success'|'error'|'warn'|''} type - 颜色类型，默认无色
      * @param {number} duration - 显示时长（ms），默认 2200
      */
     function toast(msg, type = '', duration = 2200) {
       const el = document.getElementById('ui-toast');
       if (!el) return;
       // 清除上一个 timer，实现连续 toast 时重置
       if (_toastTimer) clearTimeout(_toastTimer);
       el.textContent = msg;
       el.className = 'ui-toast' + (type ? ' ' + type : '');
       // 强制回流后再加 show，确保过渡动画触发
       void el.offsetWidth;
       el.classList.add('show');
       _toastTimer = setTimeout(() => {
         el.classList.remove('show');
         _toastTimer = null;
       }, duration);
     }

     /**
      * 显示一个自定义确认弹窗，替代 window.confirm()。
      * 返回 Promise<boolean>，用户点确认 resolve(true)，点取消 resolve(false)。
      * @param {string} title   - 弹窗标题（粗体）
      * @param {string} body    - 说明文字（可含换行）
      * @param {string} okText  - 确认按钮文字，默认"确认"
      * @param {string} cancelText - 取消按钮文字，默认"取消"
      */
     function confirm(title, body = '', okText = '确认', cancelText = '取消') {
       return new Promise(resolve => {
         const modal    = document.getElementById('confirm-modal');
         const titleEl  = document.getElementById('confirm-title');
         const bodyEl   = document.getElementById('confirm-body');
         const okBtn    = document.getElementById('confirm-ok-btn');
         const cancelBtn= document.getElementById('confirm-cancel-btn');
         if (!modal) { resolve(window.confirm(title + '\n' + body)); return; }

         titleEl.textContent = title;
         bodyEl.textContent  = body;
         okBtn.textContent   = okText;
         cancelBtn.textContent = cancelText;

         modal.classList.add('open');

         function cleanup(result) {
           modal.classList.remove('open');
           okBtn.removeEventListener('click', onOk);
           cancelBtn.removeEventListener('click', onCancel);
           resolve(result);
         }
         function onOk()     { cleanup(true);  }
         function onCancel() { cleanup(false); }
         okBtn.addEventListener('click', onOk);
         cancelBtn.addEventListener('click', onCancel);
       });
     }

     return { toast, confirm };
   })();

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
    const API = (() => {
      async function request(path, options = {}) {
        const headers = {
          'Content-Type': 'application/json',
          ...(options.headers || {}),
        };

        const token = AppState.getToken();
        if (token) {
          headers.Authorization = `Bearer ${token}`;
        }

        const resp = await fetch(`${API_BASE}${path}`, {
          method: options.method || 'GET',
          headers,
          body: options.body ? JSON.stringify(options.body) : undefined,
        });

        let data = null;
        try {
          data = await resp.json();
        } catch (_) {
          data = null;
        }

        if (!resp.ok) {
          throw new Error(data?.detail || '请求失败');
        }
        return data;
      }

      async function streamMessageToUrl(url, payload, handlers = {}) {
        const token = AppState.getToken();
        const resp = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(payload),
        });

        if (!resp.ok) {
          let data = null;
          try { data = await resp.json(); } catch (_) { data = null; }
          throw new Error(data?.detail || '流式请求失败');
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const blocks = buffer.split('\n\n');
          buffer = blocks.pop() || '';

          for (const block of blocks) {
            const lines = block.split('\n');
            let event = 'message';
            let dataLine = '';
            for (const line of lines) {
              if (line.startsWith('event: ')) event = line.slice(7).trim();
              if (line.startsWith('data: ')) dataLine += line.slice(6);
            }
            if (!dataLine) continue;
            let payloadData = null;
            try { payloadData = JSON.parse(dataLine); } catch (_) { continue; }
            if (event === 'chunk' && handlers.onChunk) handlers.onChunk(payloadData.text || '');
            if (event === 'done' && handlers.onDone) handlers.onDone(payloadData);
            if (event === 'error' && handlers.onError) handlers.onError(payloadData);
          }
        }
      }

      async function streamMessage(payload, handlers = {}) {
        return streamMessageToUrl(`${API_BASE}/chat/stream`, payload, handlers);
      }

      return {
        health: () => request('/health'),
        login:    (payload) => request('/auth/login',    { method: 'POST', body: payload }),
        register: (payload) => request('/auth/register', { method: 'POST', body: payload }),
        me: () => request('/auth/me'),
        logout: () => request('/auth/logout', { method: 'POST' }),
        getCharacters: async () => (await request('/characters')).map(normalizeCharacterCardPayload),
        getHistory: (characterId) => request(`/chat/history?character_id=${encodeURIComponent(characterId)}`),
        getCharacterProfile: (characterId) => request(`/character/profile?character_id=${encodeURIComponent(characterId)}`),
        updateCharacterProfile: (payload) => request('/character/profile', { method: 'POST', body: payload }),
        // 清空聊天并指定剧情线（greeting_index: -1=默认，>=1=alternate_greetings 对应下标）
        clearChatWithGreeting: (payload) => request('/chat/clear', { method: 'POST', body: payload }),
        sendMessage: (payload) => request('/chat/send', { method: 'POST', body: payload }),
        streamMessage,
        // 游客试聊流式接口（不需要 token）
        guestStreamMessage: (payload, handlers) => streamMessageToUrl(`${API_BASE}/chat/guest-stream`, payload, handlers),
        getGuestQuota: () => request('/chat/guest-quota'),
        // 关系状态
        getCharacterState: (characterId) => request(`/character/state?character_id=${encodeURIComponent(characterId)}`),
        // 获取角色所有开场白选项（含 alternate_greetings）
        getGreetings: (characterId) => request(`/character/greetings?character_id=${encodeURIComponent(characterId)}`),
      };
    })();

    /* ================================================================
       App 模块：路由 / 导航 / 初始化
    ================================================================ */
    const App = (() => {
      let currentPage = 'home';

      function renderNav() {
        const nav = document.getElementById('bottom-nav');
        if (!nav) return;
        nav.innerHTML = NAV_CONFIG.map(item => `
          <div class="nav-item${item.id === currentPage ? ' active' : ''}"
               data-page="${item.id}"
               onclick="App.nav('${item.id}')">
            <span class="nav-icon">${item.icon}</span>
            <span>${item.label}</span>
          </div>
        `).join('');
      }

      function nav(pageId) {
        if (pageId === 'chat' && !Chat.currentChar) {
          nav('square');
          return;
        }
        document.querySelectorAll('.page').forEach(p => {
          p.classList.toggle('active', p.id === `page-${pageId}`);
        });
        currentPage = pageId;
        renderNav();
        if (pageId !== 'chat') {
          window.scrollTo({ top: 0, behavior: 'smooth' });
        }
      }

      function navToLastChat() {
        const lastCharacterId = AppState.getLastCharacterId();
        const found = CHARACTERS.find(item => item.id === lastCharacterId);
        if (found) {
          Chat.enterChat(found);
          return;
        }
        nav('square');
      }

      async function init() {
        renderNav();
        await loadCharacters();
        Auth.bootstrap();
      }

      async function loadCharacters() {
        try {
          const characters = await API.getCharacters();
          CHARACTERS = characters;
          renderCharGrid();
        } catch (err) {
          document.getElementById('char-grid').innerHTML = `
            <div class="card" style="padding:16px;color:var(--muted);grid-column:1 / -1;">
              角色加载失败：${err.message}<br/>请先启动本地后端，再刷新页面。
            </div>
          `;
        }
      }

      return {
        nav,
        navToLastChat,
        init,
        loadCharacters,
        get currentPage() { return currentPage; },
      };
    })();

    /* ================================================================
       Chat 模块：聊天页核心逻辑（正式版最小链路）
    ================================================================ */
    const Chat = (() => {
      let currentChar = null;
      let isSending = false;
      let history = [];

      let guestQuota = null;

      /** 渲染游客体验额度提示（仅游客可见）。 */
      function renderGuestQuotaBar(quota = guestQuota) {
        if (Auth.isLoggedIn()) {
          // 已登录：隐藏游客提示
          const bar = document.getElementById('guest-trial-bar');
          if (bar) bar.style.display = 'none';
          return;
        }

        guestQuota = quota || guestQuota;
        let bar = document.getElementById('guest-trial-bar');
        if (!bar) {
          bar = document.createElement('div');
          bar.id = 'guest-trial-bar';
          bar.className = 'guest-trial-bar';
          const chatPage = document.getElementById('page-chat');
          const topbar = chatPage?.querySelector('.chat-topbar');
          if (topbar) {
            topbar.after(bar);
          } else if (chatPage) {
            chatPage.prepend(bar);
          }
        }

        const statusText = guestQuota?.status_text || '额度充足';
        const remainingPercent = Number.isFinite(guestQuota?.remaining_percent)
          ? Math.max(0, Math.min(100, guestQuota.remaining_percent))
          : 100;
        const statusClass = statusText.includes('已用完')
          ? 'exhausted'
          : (statusText.includes('不多') ? 'warning' : 'ok');

        bar.style.display = '';
        bar.innerHTML = `
          <div class="trial-copy">
            <span class="trial-label">游客体验额度</span>
            <span class="trial-status ${statusClass}">${statusText}</span>
          </div>
          <div class="trial-meter"><span style="width:${remainingPercent}%"></span></div>
          <button class="trial-login-btn" onclick="Auth.openLogin()">登录保存记录</button>
        `;
      }

      async function refreshGuestQuota() {
        if (Auth.isLoggedIn()) {
          renderGuestQuotaBar(null);
          return null;
        }
        try {
          const quota = await API.getGuestQuota();
          renderGuestQuotaBar(quota);
          return quota;
        } catch (_) {
          renderGuestQuotaBar(guestQuota || { status_text: '额度充足', remaining_percent: 100 });
          return guestQuota;
        }
      }

      /* ── 关系状态栏渲染 ─────────────────────────────────────────── */
      const PHASE_LABELS = {
        stranger: '陌生人', acquaintance: '普通朋友', friend: '好友', lover: '恋人',
      };
      const MOOD_LABELS = {
        neutral: '平静', happy: '开心', warm: '温柔', melting: '心动',
        cold: '冷淡', angry: '生气', sad: '难过', shy: '害羞', surprised: '惊讶',
      };
      const MOOD_CLASSES = Object.keys(MOOD_LABELS);

      function renderStateBar(state) {
        const barEl = document.getElementById('chat-state-bar');
        if (!barEl || !state) return;

        const affection = Math.max(0, Math.min(100, state.affection || 0));
        const phase = state.story_phase || 'stranger';
        const mood = state.mood || 'neutral';

        // 好感度条
        const fill = document.getElementById('affection-bar-fill');
        if (fill) {
          fill.style.width = affection + '%';
          fill.classList.toggle('full', affection >= 100);
        }
        const valEl = document.getElementById('affection-value');
        if (valEl) valEl.textContent = affection;

        // 阶段 pill
        const phaseEl = document.getElementById('state-phase');
        if (phaseEl) phaseEl.textContent = PHASE_LABELS[phase] || phase;

        // 心情 pill（更新颜色 class）
        const moodEl = document.getElementById('state-mood');
        if (moodEl) {
          moodEl.textContent = MOOD_LABELS[mood] || mood;
          MOOD_CLASSES.forEach(m => moodEl.classList.remove('mood-' + m));
          if (mood !== 'neutral') moodEl.classList.add('mood-' + mood);
        }

        barEl.style.display = '';
      }

      async function loadCharacterState(characterId) {
        try {
          const result = await API.getCharacterState(characterId);
          renderStateBar(result?.state);
        } catch (_) {
          // 未登录或接口出错时静默忽略，不影响正常聊天
        }
      }

      /* ── 角色状态面板（解析 AI 输出里的状态栏块） ───────────────── */
      const CharStatusPanel = (() => {
        // 是否已折叠（默认收起）
        let _collapsed = true;

        /**
         * 从 AI 输出文本里剥离状态栏内容。
         * 支持以下格式（按优先级）：
         *   ① <状态栏开始> ... <状态栏结束>  (XML标签)
         *   ② --- + **XX状态栏** 开头段落  (姜禾风格，--- 分割线后接状态栏)
         *   ③ 【状态栏】... 开头段落  (白邬风格，中括号标记)
         *   ④ **状态栏** / **状态信息** 独立行  (通用Markdown)
         *
         * 返回 { cleanText: string, statusRaw: string|null }
         */
        function stripStatusBlock(text) {
          if (!text) return { cleanText: text, statusRaw: null };

          // 格式①：XML 标签包裹
          const xmlRe = /<(?:状态栏开始|状态栏-开始|状态开始)[^>]*>([\s\S]*?)<(?:状态栏结束|状态栏-结束|状态结束)[^>]*>/i;
          const xmlMatch = text.match(xmlRe);
          if (xmlMatch) {
            const statusRaw = xmlMatch[1].trim();
            const cleanText = text.replace(xmlMatch[0], '').replace(/\n{3,}/g, '\n\n').trim();
            return { cleanText, statusRaw };
          }

          // 格式②：--- 分割线之后的内容（姜禾：用 --- 把对话和状态栏分开）
          // 匹配：前面有对话，然后是 \n---\n 或 \n---（结尾），后面是状态栏
          const hrRe = /\n---+\n([\s\S]*)$/;
          const hrMatch = text.match(hrRe);
          if (hrMatch) {
            const afterHr = hrMatch[1].trim();
            // 判断 --- 后面是否是状态栏（含"状态栏"关键词，或大量字段格式）
            if (/状态栏|状态信息|状态\s*[\|｜]|心情[：:]/i.test(afterHr)) {
              const statusRaw = afterHr;
              const cleanText = text.slice(0, text.lastIndexOf('\n---')).trim();
              return { cleanText, statusRaw };
            }
          }

          // 格式③：【状态栏】开头（白邬风格，可能在正文中间或末尾）
          // 匹配整行是 【状态栏】... 或 【XX状态栏】...
          const bracketRe = /(?:^|\n)(【[^】]*状态[^】]*】[\s\S]*)$/;
          const bracketMatch = text.match(bracketRe);
          if (bracketMatch) {
            const statusRaw = bracketMatch[1].trim();
            const matchStart = text.lastIndexOf(bracketMatch[1]);
            const cleanText = text.slice(0, matchStart).trim();
            return { cleanText, statusRaw };
          }

          // 格式④：**状态栏** / **状态信息** / **角色状态** 独立行开头
          // 也匹配 **姜禾状态栏** 这种带角色名的变体
          const mdRe = /(?:^|\n)(\*{0,2}[^\n*]{0,10}状态栏\*{0,2})\s*\n([\s\S]*)$/;
          const mdMatch = text.match(mdRe);
          if (mdMatch) {
            // 把标题行也并入 statusRaw
            const statusRaw = (mdMatch[1] + '\n' + mdMatch[2]).trim();
            const matchStart = text.indexOf(mdMatch[0]);
            const cleanText = text.slice(0, matchStart + (mdMatch[0].startsWith('\n') ? 1 : 0)).trim();
            return { cleanText: cleanText.replace(/\n{2,}$/g, '').trim(), statusRaw };
          }

          // 没有检测到状态栏
          return { cleanText: text, statusRaw: null };
        }

        /**
         * 把状态栏原始文本解析成字段数组。
         * 支持的行格式（宽松匹配）：
         *   **姓名：** 姜禾
         *   姓名：姜禾
         *   ▷ 白邬内心安全感：28  (▷ 符号开头)
         *   年龄：18岁 | 身高：165cm | 体重：42kg  (单行多字段用 | 分隔)
         *   <姓名>姜禾</姓名>
         * 返回 [{ key: string, val: string }, ...]
         */
        function parseFields(raw) {
          if (!raw) return [];
          const fields = [];

          // 先把 XML 子标签包裹的内容平铺出来
          let text = raw.replace(/<([^/][^>]*)>([\s\S]*?)<\/\1>/g, (_, tag, content) => {
            return `${tag}：${content.trim()}`;
          });

          // 去掉 【状态栏】日期时间标题行（白邬风格标题行，不是字段）
          text = text.replace(/^【[^】]*】[^\n]*\n?/m, '');

          // 按行解析
          const lines = text.split('\n');
          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) continue;

            // 去掉 ▷ 符号前缀（白邬风格）
            const noArrow = trimmed.replace(/^[▷►>→]\s*/, '');

            // 检查是否是单行多字段（用 | 或 ｜ 分隔）
            // 例如：年龄：18岁 | 身高：165cm | 体重：42kg
            if (/[|｜]/.test(noArrow)) {
              const parts = noArrow.split(/[|｜]/);
              let hasFields = false;
              for (const part of parts) {
                const m = part.trim().match(/^([^：:]+)[：:]\s*(.+)$/);
                if (m) {
                  const key = m[1].trim().replace(/^\*+|\*+$/g, '').replace(/^【|】$/g, '');
                  const val = m[2].trim().replace(/^\*+|\*+$/g, '');
                  if (key && val) { fields.push({ key, val }); hasFields = true; }
                }
              }
              if (hasFields) continue;
            }

            // 单字段行：**key:** val  /  key：val  /  key:val
            const m = noArrow.match(/^\*{0,2}([^*：:【】\n]{1,20})\*{0,2}[：:]\*{0,2}\s*([\s\S]*)$/);
            if (m) {
              const key = m[1].trim().replace(/^【|】$/g, '');
              const val = m[2].trim().replace(/^\*+|\*+$/g, '');
              if (key && val) fields.push({ key, val });
            }
          }
          return fields;
        }

        // 哪些字段要用「整行」宽格式展示
        const FULL_WIDTH_KEYS = ['隐藏想法', '内心想法', '对你的认知', '想法', '物品携带', '随身物品', '物品'];
        // 哪些字段是心情（特殊颜色）
        const MOOD_KEYS = ['当前心情', '心情', 'mood'];

        /**
         * 渲染角色状态面板。
         * @param {string|null} statusRaw  状态栏原始文本，null 表示本轮没有状态栏
         * @param {boolean} keepIfEmpty    true 时若 statusRaw 为 null 保留上次内容
         */
        function render(statusRaw, keepIfEmpty = true) {
          const panel = document.getElementById('char-status-panel');
          if (!panel) return;

          if (!statusRaw) {
            if (!keepIfEmpty) panel.style.display = 'none';
            return; // 保留上次内容
          }

          const fields = parseFields(statusRaw);
          if (!fields.length) {
            panel.style.display = 'none';
            return;
          }

          const body = document.getElementById('csp-body');
          if (!body) return;
          body.innerHTML = '';

          fields.forEach(({ key, val }) => {
            const isFull = FULL_WIDTH_KEYS.some(k => key.includes(k));
            const isMood = MOOD_KEYS.some(k => key.includes(k));
            const div = document.createElement('div');
            div.className = 'csp-field' + (isFull ? ' full-width' : '') + (isMood ? ' mood' : '');

            const keyEl = document.createElement('span');
            keyEl.className = 'csp-key';
            keyEl.textContent = key + '：';

            const valEl = document.createElement('span');
            valEl.className = 'csp-val';
            valEl.textContent = val;

            div.appendChild(keyEl);
            div.appendChild(valEl);
            body.appendChild(div);
          });

          panel.style.display = '';
          // 同步折叠状态（首次渲染时保持默认收起）
          const bodyEl2 = document.getElementById('csp-body');
          const arrowEl2 = document.getElementById('csp-arrow');
          if (bodyEl2) bodyEl2.classList.toggle('collapsed', _collapsed);
          if (arrowEl2) arrowEl2.classList.toggle('collapsed', _collapsed);
        }

        /** 切换折叠状态 */
        function toggle() {
          _collapsed = !_collapsed;
          const body = document.getElementById('csp-body');
          const arrow = document.getElementById('csp-arrow');
          if (body) body.classList.toggle('collapsed', _collapsed);
          if (arrow) arrow.classList.toggle('collapsed', _collapsed);
        }

        /** 进入新角色时隐藏面板，清空内容 */
        function reset() {
          const panel = document.getElementById('char-status-panel');
          if (panel) panel.style.display = 'none';
          const body = document.getElementById('csp-body');
          if (body) body.innerHTML = '';
          _collapsed = true;
          const arrow = document.getElementById('csp-arrow');
          if (arrow) arrow.classList.add('collapsed');
          const bodyEl = document.getElementById('csp-body');
          if (bodyEl) bodyEl.classList.add('collapsed');
        }

        return { stripStatusBlock, render, toggle, reset };
      })();

      async function enterChat(char) {
        currentChar = normalizeCharacter(char);
        history = [];
        AppState.setLastCharacterId(currentChar.id);
        updateChatHeader(currentChar);
        document.getElementById('chat-messages').innerHTML = '';
        appendDateDivider();
        // 重置角色状态面板（换角色时清空上一个角色的状态）
        CharStatusPanel.reset();
        App.nav('chat');

        if (!Auth.isLoggedIn()) {
          // 游客模式：不加载历史，直接展示开场白（从角色数据里取）
          const openingText = currentChar.opening_message || currentChar.first_message || '';
          if (openingText) {
            appendMsg('assistant', openingText);
            history.push({ role: 'assistant', content: openingText });
          } else {
            appendMsg('assistant', `你好，我是${currentChar.display_name || currentChar.name}。`);
          }
          refreshGuestQuota();
          return;
        }

        // 已登录：正常加载后端历史
        appendLoadingHint('正在读取历史记录…');

        try {
          const result = await API.getHistory(currentChar.id);
          const mergedChar = normalizeCharacter(result.character || currentChar);
          currentChar = { ...currentChar, ...mergedChar };
          history = result.messages || [];
          updateChatHeader(currentChar);
          renderHistory(history);
          // 异步加载关系状态（不阻塞主流程）
          loadCharacterState(currentChar.id);
        } catch (err) {
          document.getElementById('chat-messages').innerHTML = '';
          appendDateDivider();
          appendMsg('assistant', `⚠ 历史读取失败：${err.message}`);
        }
      }

      function normalizeCharacter(char = {}) {
        return normalizeCharacterCardPayload({
          ...char,
          display_name: char.display_name || char.remark || char.name || '角色',
          sign: char.sign || char.custom_signature || char.subtitle || '',
          remark: char.remark || '',
          custom_signature: char.custom_signature || '',
        });
      }

      function updateChatHeader(char) {
        const avatarEl = document.getElementById('chat-avatar');
        // 优先用 avatarImg（/api/avatar/xxx），兼容旧 coverImg
        const SERVER_ORIGIN = typeof API_BASE !== 'undefined' ? API_BASE.replace(/\/api$/, '') : '';
        const rawImg = char.avatarImg || char.coverImg || null;
        const imgSrc = rawImg
          ? (rawImg.startsWith('/') ? SERVER_ORIGIN + rawImg : rawImg)
          : null;
        const fallbackChar = char.abbr || (char.display_name || char.name || '角')[0];
        const fallbackBg = char.color || 'linear-gradient(135deg,#8a72ff,#ff7eb6)';

        if (imgSrc) {
          const img = document.createElement('img');
          img.src = imgSrc;
          img.alt = char.display_name || char.name || '';
          img.style.cssText = 'width:100%;height:100%;object-fit:cover;border-radius:inherit';
          img.onerror = () => {
            avatarEl.textContent = fallbackChar;
            avatarEl.style.background = fallbackBg;
          };
          avatarEl.innerHTML = '';
          avatarEl.style.background = 'none';
          avatarEl.appendChild(img);
        } else {
          avatarEl.textContent = fallbackChar;
          avatarEl.style.background = fallbackBg;
        }

        const displayName = char.display_name || char.name;
        const rawNameEl = document.getElementById('chat-raw-name');
        document.getElementById('chat-name').textContent = displayName;
        if (char.remark && char.name && char.remark !== char.name) {
          rawNameEl.textContent = `原名：${char.name}`;
          rawNameEl.classList.add('show');
        } else {
          rawNameEl.textContent = '';
          rawNameEl.classList.remove('show');
        }
        document.getElementById('chat-sign').innerHTML = `<span class="online-dot"></span>${char.sign || char.subtitle || ''}`;
      }

      function appendDateDivider() {
        const div = document.createElement('div');
        div.className = 'date-divider';
        div.textContent = formatDate(new Date());
        document.getElementById('chat-messages').appendChild(div);
      }

      function appendLoadingHint(text) {
        const row = document.createElement('div');
        row.className = 'date-divider';
        row.textContent = text;
        document.getElementById('chat-messages').appendChild(row);
      }

      function appendMsg(role, text, createdAt = null, retryText = null) {
        const normalizedRole = role === 'ai' ? 'assistant' : role;
        const isError = normalizedRole === 'error';
        const box = document.getElementById('chat-messages');
        const row = document.createElement('div');
        // 错误消息显示在 ai 侧
        row.className = `msg-row ${(normalizedRole === 'assistant' || isError) ? 'ai' : normalizedRole}`;

        const bubble = document.createElement('div');
        if (isError) {
          bubble.className = 'msg-bubble error-bubble';
          bubble.innerHTML = `⚠ ${escapeHtml(text)}`;
          // 如果有重试文本，加重试按钮
          if (retryText) {
            const btn = document.createElement('div');
            btn.className = 'retry-btn';
            btn.textContent = '🔄 重新发送';
            btn.addEventListener('click', () => {
              row.remove();
              // 把重试文本写回输入框并触发发送
              const input = document.getElementById('chat-input');
              input.value = retryText;
              send();
            });
            bubble.appendChild(document.createElement('br'));
            bubble.appendChild(btn);
          }
        } else {
          bubble.className = `msg-bubble ${normalizedRole === 'assistant' ? 'ai' : normalizedRole}`;
          renderTextWithLineBreaks(bubble, text, normalizedRole === 'assistant');
          const doCopy = () => {
            navigator.clipboard.writeText(text).then(() => showCopyToast());
          };
          bubble.addEventListener('dblclick', doCopy);
          let pressTimer;
          bubble.addEventListener('touchstart', () => { pressTimer = setTimeout(doCopy, 600); }, { passive: true });
          bubble.addEventListener('touchend', () => clearTimeout(pressTimer), { passive: true });
          bubble.addEventListener('touchmove', () => clearTimeout(pressTimer), { passive: true });
        }

        const time = document.createElement('div');
        time.className = 'msg-time';
        time.textContent = formatTime(createdAt ? new Date(createdAt) : new Date());

        row.appendChild(bubble);
        row.appendChild(time);
        box.appendChild(row);
        scrollToBottom();
        return row;
      }

      function renderTextWithLineBreaks(el, text, isAssistant = false) {
        el.innerHTML = '';
        // assistant 消息才做状态栏剥离
        let displayText = text;
        if (isAssistant) {
          const { cleanText, statusRaw } = CharStatusPanel.stripStatusBlock(text);
          displayText = cleanText;
          // 有状态栏时更新面板（流式过程中可能多次调用，每次都更新）
          if (statusRaw !== null) {
            CharStatusPanel.render(statusRaw);
          }
        }
        const cleaned = String(displayText).replace(/\n{2,}/g, '\n').trim();
        const lines = cleaned.split('\n');
        lines.forEach((line, i) => {
          el.appendChild(document.createTextNode(line));
          if (i < lines.length - 1) el.appendChild(document.createElement('br'));
        });
      }

      function showCopyToast() {
        const toast = document.getElementById('copy-toast');
        if (!toast) return;
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 1800);
      }

      function showTyping() {
        const box = document.getElementById('chat-messages');
        const row = document.createElement('div');
        row.className = 'msg-row ai';
        row.id = 'typing-row';
        const bubble = document.createElement('div');
        bubble.className = 'msg-bubble typing';
        bubble.innerHTML = `
          <span class="typing-dot"></span>
          <span class="typing-dot"></span>
          <span class="typing-dot"></span>
        `;
        row.appendChild(bubble);
        box.appendChild(row);
        scrollToBottom();
      }

      function removeTyping() {
        const el = document.getElementById('typing-row');
        if (el) el.remove();
      }

      function createStreamRow() {
        const box = document.getElementById('chat-messages');
        const row = document.createElement('div');
        row.className = 'msg-row ai';

        const bubble = document.createElement('div');
        bubble.className = 'msg-bubble ai';
        bubble.textContent = '';

        const time = document.createElement('div');
        time.className = 'msg-time';
        time.textContent = formatTime(new Date());

        row.appendChild(bubble);
        row.appendChild(time);
        box.appendChild(row);
        scrollToBottom();
        return bubble;
      }

      function renderHistory(messages) {
        const box = document.getElementById('chat-messages');
        box.innerHTML = '';
        appendDateDivider();
        messages.forEach(item => appendMsg(item.role, item.content, item.created_at));
        scrollToBottom();
      }

      async function refreshCurrentCharacterProfile() {
        if (!currentChar) return null;
        const result = await safeApiCall(() => API.getCharacterProfile(currentChar.id));
        currentChar = normalizeCharacter(result.character || currentChar);
        updateChatHeader(currentChar);
        syncCharacterInList(currentChar);
        return currentChar;
      }

      function getDisplayMeta() {
        if (!currentChar) {
          return { displayName: 'TA', rawName: '', sign: '' };
        }
        return {
          displayName: currentChar.display_name || currentChar.remark || currentChar.name || 'TA',
          rawName: currentChar.name || '',
          sign: currentChar.sign || currentChar.custom_signature || currentChar.subtitle || '',
        };
      }

      function syncCharacterInList(updatedChar) {
        if (!updatedChar?.id) return;
        CHARACTERS = CHARACTERS.map(item => item.id === updatedChar.id ? { ...item, ...updatedChar } : item);
      }

      function applyCharacterProfile(payload = {}) {
        if (!currentChar) return;
        currentChar = normalizeCharacter({ ...currentChar, ...payload });
        updateChatHeader(currentChar);
        syncCharacterInList(currentChar);
      }

      async function clearCurrentChat() {
        if (!currentChar) return;
        await safeApiCall(() => API.clearChatWithGreeting({ character_id: currentChar.id, greeting_index: -1 }));
        await enterChat(currentChar);
      }

      async function send() {
        if (isSending) return;
        if (!currentChar) return;

        const input = document.getElementById('chat-input');
        const text = input.value.trim();
        if (!text) return;

        appendMsg('user', text);
        input.value = '';
        input.style.height = 'auto';
        setSending(true);
        showTyping();
        // 移动端发送后不立即 focus（避免键盘弹起遮盖内容），桌面端保持 focus
        if (window.innerWidth > 500) input.focus();

        let bubbleEl = null;
        let aiText = '';

        try {
          if (!Auth.isLoggedIn()) {
            // 游客模式：把本地 history 中最近 8 条传给后端
            const guestHistory = history.slice(-8).map(m => ({ role: m.role, content: m.content }));
            await API.guestStreamMessage(
              {
                character_id: currentChar.id,
                message: text,
                guest_history: guestHistory,
              },
              {
                onChunk(chunk) {
                  if (!chunk) return;
                  if (!bubbleEl) {
                    removeTyping();
                    bubbleEl = createStreamRow();
                  }
                  aiText += chunk;
                  renderTextWithLineBreaks(bubbleEl, aiText, true);
                  scrollToBottom();
                },
                onDone(payload) {
                  if (!bubbleEl) {
                    removeTyping();
                    bubbleEl = createStreamRow();
                    aiText = payload?.reply || '';
                  }
                  aiText = payload?.reply || aiText;
                  renderTextWithLineBreaks(bubbleEl, aiText, true);
                  // 游客：存本地 history（不存服务端）
                  history.push({ role: 'user', content: text, created_at: new Date().toISOString() });
                  history.push({ role: 'assistant', content: aiText, created_at: new Date().toISOString() });
                },
                // AI 调用失败时，后端不发 chunk/done，只发 error 事件
                onError(payload) {
                  removeTyping();
                  // 删除整个 AI 消息行（如果已创建的话）
                  if (bubbleEl && bubbleEl.parentNode) {
                    bubbleEl.parentNode.remove();
                  }
                  bubbleEl = null;
                  UI.toast(payload?.message || '网络波动，请稍后再试', 'warn', 3000);
                },
              }
            );
            await refreshGuestQuota();
          } else {
            // 已登录：走正式流
            await API.streamMessage(
              {
                character_id: currentChar.id,
                message: text,
              },
              {
                onChunk(chunk) {
                  if (!chunk) return;
                  if (!bubbleEl) {
                    removeTyping();
                    bubbleEl = createStreamRow();
                  }
                  aiText += chunk;
                  renderTextWithLineBreaks(bubbleEl, aiText, true);
                  scrollToBottom();
                },
                onDone(payload) {
                  if (!bubbleEl) {
                    removeTyping();
                    bubbleEl = createStreamRow();
                    aiText = payload?.reply || '';
                  }
                  aiText = payload?.reply || aiText;
                  renderTextWithLineBreaks(bubbleEl, aiText, true);
                  history.push({ role: 'user', content: text, created_at: new Date().toISOString() });
                  history.push({ role: 'assistant', content: aiText, created_at: new Date().toISOString() });
                  // 如果 AI 输出里包含状态增量，后端已经更新 DB 并在 done 事件里返回最新状态
                  if (payload?.character_state) {
                    renderStateBar(payload.character_state);
                  }
                },
                // AI 调用失败时，后端不发 chunk/done，只发 error 事件
                onError(payload) {
                  removeTyping();
                  // 删除整个 AI 消息行（如果已创建的话）
                  if (bubbleEl && bubbleEl.parentNode) {
                    bubbleEl.parentNode.remove();
                  }
                  bubbleEl = null;
                  UI.toast(payload?.message || '网络波动，请稍后再试', 'warn', 3000);
                },
              }
            );
          }
        } catch (err) {
          if (!Auth.isLoggedIn()) {
            await refreshGuestQuota();
            if ((err.message || '').includes('额度已用完')) {
              UI.toast('今日游客体验额度已用完，登录后可继续聊天', 'warn', 3200);
              setTimeout(() => Auth.openLogin(), 800);
            } else if ((err.message || '').includes('发送太快')) {
              UI.toast('发送太快了，请稍后再试', 'warn', 2500);
            }
          }
          removeTyping();
          appendMsg('error', `发送失败：${err.message}`, null, text);
        } finally {
          removeTyping();
          setSending(false);
        }
      }

      function setSending(bool) {
        isSending = bool;
        const btn = document.getElementById('send-btn');
        btn.disabled = bool;
        btn.classList.toggle('loading', bool);
      }

      function scrollToBottom() {
        const box = document.getElementById('chat-messages');
        box.scrollTop = box.scrollHeight;
      }

      return {
        enterChat,
        send,
        refreshCurrentCharacterProfile,
        applyCharacterProfile,
        clearCurrentChat,
        getDisplayMeta,
        renderGuestQuotaBar,
        refreshGuestQuota,
        toggleStatusPanel: CharStatusPanel.toggle,
        get currentChar() { return currentChar; },
        get history() { return history; },
      };
    })();

    /* ================================================================
       CharDetail 模块：角色详情弹窗
    ================================================================ */
    const CharDetail = (() => {
      let pendingChar = null;

      function open(char) {
        pendingChar = char;
        const cover = document.getElementById('detail-cover');
        cover.style.background = char.color || 'linear-gradient(135deg,#8a72ff,#ff7eb6)';
        // 优先用 avatarImg（/api/avatar/xxx 路由），和广场页保持一致
        const SERVER_ORIGIN = API_BASE.replace(/\/api$/, '');
        const rawCover = char.coverImg || char.avatarImg || null;
        const imgSrc = rawCover
          ? (rawCover.startsWith('/') ? SERVER_ORIGIN + rawCover : rawCover)
          : null;
        if (imgSrc) {
          cover.style.backgroundImage = `url(${imgSrc})`;
          cover.style.backgroundSize = 'cover';
          cover.style.backgroundPosition = 'center top';
        } else {
          cover.style.backgroundImage = '';
          cover.style.backgroundPosition = '';
        }

        const displayName = char.display_name || char.remark || char.name;
        // 详情页顶部签名：优先 custom_signature，否则用 subtitle（简介），不用旧的 sign 字段
        const signText = char.custom_signature || char.subtitle || '';
        const isAliased = char.remark && char.name && char.remark !== char.name;
        document.getElementById('detail-name').innerHTML = isAliased
          ? `${escapeHtml(displayName)}<div style="font-size:12px;color:rgba(255,255,255,.72);font-weight:500;margin-top:4px;">原名：${escapeHtml(char.name)}</div>`
          : escapeHtml(displayName);
        document.getElementById('detail-sign').textContent = signText;

        // ── 卡类型徽章 ──────────────────────────────────────────────────
        const TYPE_META = {
          intimate:   { icon: '💞', label: '对话陪伴', btnText: '开始聊天 →' },
          scenario:   { icon: '🎭', label: '剧情沙盒', btnText: '进入剧情 →' },
          world:      { icon: '🌐', label: '世界探索', btnText: '进入世界 →' },
          divination: { icon: '🔮', label: '占卜形象', btnText: '开始占卜 →' },
        };
        const cardType = char.card_type || 'intimate';
        const typeMeta = TYPE_META[cardType] || TYPE_META.intimate;

        // 标签行：类型徽章 + 角色原有标签
        const typeBadgeHtml = `<span class="char-detail-tag detail-type-badge ${cardType}">${typeMeta.icon} ${typeMeta.label}</span>`;
        document.getElementById('detail-tags').innerHTML =
          typeBadgeHtml +
          (char.tags || []).map(t => `<span class="char-detail-tag">${t}</span>`).join('');

        // 「关于他」：用 subtitle（自动提取的简短介绍），而不是超长人设档案
        document.getElementById('detail-bio').textContent = char.subtitle || char.bio?.slice(0, 120) || '';

        // ── 开场白预览 ───────────────────────────────────────────────────
        const openingSection = document.getElementById('detail-opening-section');
        const openingEl = document.getElementById('detail-opening');
        const openingText = char.opening_message || char.first_message || '';
        if (openingText && openingText.length > 5) {
          // 最多展示前 200 个字，保持预览简洁
          const previewText = openingText.length > 200 ? openingText.slice(0, 200).trimEnd() + '…' : openingText;
          openingEl.textContent = previewText;
          openingSection.style.display = '';
        } else {
          openingSection.style.display = 'none';
        }

        // 按钮文字根据类型变化
        const chatBtn = document.getElementById('detail-chat-btn');
        if (chatBtn) chatBtn.textContent = typeMeta.btnText;

        document.getElementById('char-detail-modal').classList.add('open');
      }

      function close(e) {
        if (e && e.target !== document.getElementById('char-detail-modal')) return;
        document.getElementById('char-detail-modal').classList.remove('open');
      }

      function startChat() {
        document.getElementById('char-detail-modal').classList.remove('open');
        if (!pendingChar) return;

        // 游客未登录：直接进聊天（用默认开场白，不弹剧情线选择）
        if (!Auth.isLoggedIn()) {
          Chat.enterChat(pendingChar);
          return;
        }

        // 已登录：查询该角色有多少条开场白选项
        API.getGreetings(pendingChar.id).then(result => {
          const greetings = result?.greetings || [];
          if (greetings.length > 1) {
            GreetingSelect.open(pendingChar, greetings);
          } else {
            Chat.enterChat(pendingChar);
          }
        }).catch(() => {
          Chat.enterChat(pendingChar);
        });
      }

      return { open, close, startChat };
    })();

    /* ================================================================
       GreetingSelect 模块：多开场白剧情线选择弹窗
       打开时机：CharDetail.startChat() 发现角色有 >1 条 greetings
    ================================================================ */
    const GreetingSelect = (() => {
      let _char = null;     // 当前待进入的角色
      let _greetings = [];  // 开场白选项列表

      /**
       * 打开剧情线选择弹窗。
       * @param {object} char      - 角色对象
       * @param {Array}  greetings - 后端返回的 greetings 数组
       */
      function open(char, greetings) {
        _char = char;
        _greetings = greetings;

        // 渲染选项列表
        const listEl = document.getElementById('greeting-list');
        listEl.innerHTML = greetings.map(item => `
          <div class="greeting-item" onclick="GreetingSelect.select(${item.index})">
            <div class="greeting-item-inner">
              <div class="greeting-item-label">${escapeHtml(item.label)}</div>
              <div class="greeting-item-preview">${escapeHtml(item.preview)}</div>
            </div>
            <span class="greeting-item-arrow">›</span>
          </div>
        `).join('');

        document.getElementById('greeting-select-modal').classList.add('open');
      }

      function close(e) {
        if (e && e.target !== document.getElementById('greeting-select-modal')) return;
        document.getElementById('greeting-select-modal').classList.remove('open');
      }

      /**
       * 用户选择了某条剧情线。
       * - 若 index=0（默认），直接进入聊天（无需清空，走正常流程即可）
       * - 若 index>=1（alternate），先调清空接口指定 greeting_index，再进入聊天
       * @param {number} index - greetings 中的 index 字段
       */
      async function select(index) {
        close();
        if (!_char) return;

        const char = _char;

        if (index === 0) {
          Chat.enterChat(char);
          return;
        }

        // 非默认剧情线：先重置聊天并用指定开场白，再进入聊天页
        // （游客不应能走到这里，已在 startChat 里处理）
        try {
          await safeApiCall(() => API.clearChatWithGreeting({
            character_id: char.id,
            greeting_index: index,
          }));
        } catch (err) {
          if (err.message !== '未登录') {
            UI.toast(`切换剧情线失败：${err.message}`, 'error');
          }
          return;
        }

        Chat.enterChat(char);
      }

      return { open, close, select };
    })();

    /* ================================================================
       Auth 模块：真实登录 / 持久化登录态
    ================================================================ */
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
        AppState.setToken(result.token);
        user = {
          id: result.user.id,
          name: result.user.nickname,
          email: result.user.email,
        };
        loggedIn = true;
        AppState.setUser(user);
        closeLogin();
        renderProfile();
        // 登录后隐藏游客体验额度提示
        if (typeof Chat !== 'undefined') Chat.renderGuestQuotaBar();
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
        if (!password || password.length < 6) { UI.toast('密码至少 6 位', 'warn'); return; }

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
        if (!password || password.length < 6) { UI.toast('密码至少 6 位', 'warn'); return; }

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

        const token = AppState.getToken();
        if (!token) {
          renderProfile();
          return;
        }

        try {
          const me = await API.me();
          user = { name: me.nickname, email: me.email, id: me.id };
          loggedIn = true;
          AppState.setUser(user);
        } catch (_) {
          AppState.setToken('');
          AppState.setUser(null);
          loggedIn = false;
          user = null;
        }
        renderProfile();
      }

      async function logout() {
        try {
          if (AppState.getToken()) {
            await API.logout();
          }
        } catch (_) {}
        AppState.setToken('');
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
          document.getElementById('profile-avatar-char').textContent = (user.name || user.email || '你')[0].toUpperCase();
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

      function isLoggedIn() {
        return loggedIn;
      }

      return { openLogin, closeLogin, switchTab, doSubmit, doLogin, doRegister, logout, bootstrap, isLoggedIn };
    })();

    const ChatMenu = (() => {
      function ensureCurrentChar() {
        if (!Chat.currentChar) {
          UI.toast('请先进入一个角色聊天页。', 'warn');
          return false;
        }
        return true;
      }

      function toggle() {
        if (!ensureCurrentChar()) return;
        document.getElementById('chat-menu-overlay').classList.toggle('open');
      }

      function close(e) {
        if (e && e.target !== document.getElementById('chat-menu-overlay')) return;
        document.getElementById('chat-menu-overlay').classList.remove('open');
      }

      function renderHistoryModal() {
        const listEl = document.getElementById('history-list');
        const messages = Chat.history || [];
        if (!messages.length) {
          listEl.innerHTML = `<div class="history-empty">现在还没有聊天记录，等你们开始说话后，这里就会慢慢填满。</div>`;
          return;
        }
        const meta = Chat.getDisplayMeta();
        listEl.innerHTML = messages.map(item => `
          <div class="history-card">
            <div class="history-role ${item.role === 'user' ? 'user' : ''}">${item.role === 'user' ? '你' : meta.displayName}</div>
            <div class="history-content">${escapeHtml(item.content || '')}</div>
            <div class="history-time">${item.created_at ? formatHistoryTime(item.created_at) : '刚刚'}</div>
          </div>
        `).join('');
      }

      function openHistory() {
        close();
        if (!ensureCurrentChar()) return;
        renderHistoryModal();
        document.getElementById('history-modal').classList.add('open');
      }

      function closeHistory(e) {
        if (e && e.target !== document.getElementById('history-modal')) return;
        document.getElementById('history-modal').classList.remove('open');
      }

      function openRemark() {
        close();
        if (!ensureCurrentChar()) return;
        document.getElementById('input-remark').value = Chat.currentChar?.remark || '';
        document.getElementById('remark-modal').classList.add('open');
      }

      function closeRemark(e) {
        if (e && e.target !== document.getElementById('remark-modal')) return;
        document.getElementById('remark-modal').classList.remove('open');
      }

      async function saveRemark() {
        if (!ensureCurrentChar()) return;
        const remark = document.getElementById('input-remark').value.trim();
        try {
          const result = await safeApiCall(() => API.updateCharacterProfile({
            character_id: Chat.currentChar.id,
            remark,
            custom_signature: Chat.currentChar.custom_signature || '',
          }));
          Chat.applyCharacterProfile(result.character);
          closeRemark();
          UI.toast(remark ? '备注已保存。' : '备注已清空。', 'success');
        } catch (err) {
          if (err.message !== '未登录') UI.toast(`保存失败：${err.message}`, 'error');
        }
      }

      async function clearChat() {
        close();
        if (!ensureCurrentChar()) return;
        const meta = Chat.getDisplayMeta();
        const ok = await UI.confirm(
          `清空与${meta.displayName}的聊天记录`,
          `清空后可以重新选择剧情线开始，当前的聊天记录将无法恢复。`,
          '确认清空',
          '再想想'
        );
        if (!ok) return;
        try {
          // 先清空聊天记录（用默认开场白占位）
          await safeApiCall(() => API.clearChatWithGreeting({ character_id: Chat.currentChar.id, greeting_index: -1 }));

          // 查 greetings，有多条时让用户重选剧情线
          const result = await API.getGreetings(Chat.currentChar.id).catch(() => null);
          const greetings = result?.greetings || [];
          if (greetings.length > 1) {
            GreetingSelect.open(Chat.currentChar, greetings);
          } else {
            await Chat.enterChat(Chat.currentChar);
            UI.toast('聊天记录已清空，重新开始了。', 'success');
          }
        } catch (err) {
          if (err.message !== '未登录') UI.toast(`清空失败：${err.message}`, 'error');
        }
      }

      return {
        toggle,
        close,
        openHistory,
        closeHistory,
        openRemark,
        closeRemark,
        saveRemark,
        clearChat,
      };
    })();

    /* ================================================================
       渲染角色广场
    ================================================================ */

    function formatTime(date) {
      const h = String(date.getHours()).padStart(2, '0');
      const m = String(date.getMinutes()).padStart(2, '0');
      return `${h}:${m}`;
    }

    function formatDate(date) {
      const days = ['周日','周一','周二','周三','周四','周五','周六'];
      return `${date.getMonth()+1}月${date.getDate()}日 ${days[date.getDay()]}`;
    }

    function formatHistoryTime(value) {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return '时间未知';
      return `${formatDate(date)} ${formatTime(date)}`;
    }

    function escapeHtml(text = '') {
      return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/\n/g, '<br/>');
    }

    /* ----------------------------------------------------------------
       toggleSection(key) — 点击分区标题时展开/收起该分区卡片列表
       ---------------------------------------------------------------- */
    function toggleSection(key) {
      const body = document.getElementById(`section-body-${key}`);
      const arrow = document.getElementById(`section-arrow-${key}`);
      const header = document.getElementById(`section-header-${key}`);
      if (!body) return;
      const isOpen = body.classList.toggle('open');
      if (arrow) arrow.textContent = isOpen ? '▲' : '▼';
      if (header) header.classList.toggle('collapsed', !isOpen);
    }

    function renderCharGrid() {
      const grid = document.getElementById('char-grid');
      // 即使角色数据为空，也显示分区结构，只是内容为空

      // ── 推荐横幅（取对话陪伴分组里第一个有封面图的角色）──────────────
      const bannerEl = document.getElementById('featured-banner');
      const SERVER_ORIGIN = API_BASE.replace(/\/api$/, '');
      const featuredChar = CHARACTERS.find(c => (c.card_type || 'intimate') !== 'scenario' && (c.coverImg || c.avatarImg));
      if (bannerEl && featuredChar) {
        const imgSrc = (() => {
          const img = featuredChar.coverImg || featuredChar.avatarImg;
          if (!img) return '';
          return img.startsWith('/') ? SERVER_ORIGIN + img : img;
        })();
        const featuredName = featuredChar.display_name || featuredChar.remark || featuredChar.name || '';
        const featuredSub = featuredChar.subtitle || '';
        const featuredIdx = CHARACTERS.indexOf(featuredChar);
        bannerEl.style.display = '';
        bannerEl.innerHTML = `
          <div class="featured-banner-card" onclick="CharDetail.open(CHARACTERS[${featuredIdx}])">
            <div class="featured-banner-bg" style="background-color:${featuredChar.color || '#1a1b30'};${imgSrc ? `background-image:url(${imgSrc});` : ''}"></div>
            <button class="featured-banner-btn" onclick="event.stopPropagation();Chat.enterChat(CHARACTERS[${featuredIdx}])">立即聊天</button>
            <div class="featured-banner-content">
              <div class="featured-banner-label">✦ 今日推荐</div>
              <div class="featured-banner-name">${escapeHtml(featuredName)}</div>
              ${featuredSub ? `<div class="featured-banner-sub">${escapeHtml(featuredSub)}</div>` : ''}
            </div>
          </div>
        `;
      } else if (bannerEl) {
        bannerEl.style.display = 'none';
      }

      // ── 三分区元信息配置 ──────────────────────────────────────────────
      // key 对应分区 ID，title 是标题，desc 是副标题，gradient 是主题色渐变
      const SECTION_META = {
        intimate: {
          icon: '💞', title: '对话陪伴',
          desc: '专属 AI 角色，沉浸式长期陪伴',
          gradient: 'linear-gradient(90deg, rgba(255,94,158,.18), transparent)',
          accentColor: 'rgba(255,126,182,.8)',
        },
        scenario: {
          icon: '🎭', title: '剧情沙盒',
          desc: '多线分支剧情，解锁角色专属故事线',
          gradient: 'linear-gradient(90deg, rgba(123,92,255,.18), transparent)',
          accentColor: 'rgba(138,114,255,.8)',
        },
        world: {
          icon: '🌐', title: '世界探索',
          desc: '沉浸式世界观系统，自由探索设定宇宙',
          gradient: 'linear-gradient(90deg, rgba(16,185,129,.18), transparent)',
          accentColor: 'rgba(52,211,153,.8)',
        },
        divination: {
          icon: '🔮', title: '占卜形象',
          desc: '星座运势、塔罗牌占卜、神秘灵性体验',
          gradient: 'linear-gradient(90deg, rgba(56,189,248,.15), transparent)',
          accentColor: 'rgba(126,231,195,.8)',
        },
      };

      // 卡类型元信息（用于卡片徽章）
      const TYPE_META = {
        intimate:   { icon: '💞', label: '对话陪伴', desc: '专属陪伴' },
        scenario:   { icon: '🎭', label: '剧情沙盒', desc: '多线分支' },
        world:      { icon: '🌐', label: '世界探索', desc: '自由探索' },
        divination: { icon: '🔮', label: '占卜形象', desc: '灵性体验' },
      };

      // 按 card_type 分组：每种类型独立分区
      const groups = { intimate: [], scenario: [], world: [], divination: [] };
      CHARACTERS.forEach((char, i) => {
        if (char.card_type === 'scenario') {
          groups.scenario.push({ char, i });
        } else if (char.card_type === 'world') {
          groups.world.push({ char, i });
        } else if (char.card_type === 'divination') {
          groups.divination.push({ char, i });
        } else {
          // 对话陪伴 / 未知 → intimate 分区
          groups.intimate.push({ char, i });
        }
      });

      // ── 渲染单张角色卡片 ─────────────────────────────────────────────
      function renderCard({ char, i }) {
        const cardType = char.card_type || 'intimate';
        const typeMeta = TYPE_META[cardType] || TYPE_META.intimate;
        const displayName = char.display_name || char.remark || char.name;
        const isAliased = char.remark && char.name && char.remark !== char.name;
        const nameHtml = isAliased
          ? `${escapeHtml(displayName)}<small>原名：${escapeHtml(char.name)}</small>`
          : escapeHtml(displayName || '未命名角色');
        const bioText = char.subtitle || (char.bio ? char.bio.slice(0, 80) : '');
        const warningLabel = char.has_import_warning ? `<span class="char-tag warning-tag">需检查</span>` : '';
        const SERVER_ORIGIN = API_BASE.replace(/\/api$/, '');
        const coverStyle = (() => {
          const img = char.coverImg || char.avatarImg;
          if (img) {
            const imgUrl = img.startsWith('/') ? SERVER_ORIGIN + img : img;
            return `background:${char.color || 'linear-gradient(135deg,#7b5cff,#ff7eb6)'};background-image:url(${imgUrl});background-size:cover;background-position:center top`;
          }
          return `background:${char.color || 'linear-gradient(135deg,#7b5cff,#ff7eb6)'}`;
        })();

        return `
          <div class="char-card" onclick="CharDetail.open(CHARACTERS[${i}])">
            <div class="char-cover" style="${coverStyle}">
              <span class="type-badge ${cardType}">${typeMeta.icon} ${typeMeta.label}</span>
              ${char.free ? '<span class="free-badge">免费</span>' : ''}
            </div>
            <div class="char-info" style="padding:10px 12px 12px">
              <div class="char-name">${nameHtml}</div>
              <div class="char-bio">${escapeHtml(bioText || '暂无简介')}</div>
              <div class="char-tags" style="margin-top:8px">
                ${warningLabel}
                ${(char.tags || []).slice(0,2).map(t => `<span class="char-tag">${t}</span>`).join('')}
              </div>
            </div>
          </div>
        `;
      }

      // ── 渲染占卜星象分区的占位模板卡 ────────────────────────────────
      // 内容暂未上线，只搭框架，点击后提示"即将推出"
      const DIVINATION_TEMPLATES = [
        {
          icon: '♈', name: '今日星座',
          desc: '12星座每日运势，爱情事业详解',
          gradient: 'linear-gradient(135deg,#7b3fcb,#c362ff)',
          tags: ['星座', '运势'],
          coming: true,
        },
        {
          icon: '🃏', name: '塔罗牌占卜',
          desc: '经典78张塔罗，揭示内心深处的答案',
          gradient: 'linear-gradient(135deg,#1a3a5c,#2e78c8)',
          tags: ['塔罗', '占卜'],
          coming: true,
        },
      ];

      function renderDivinationTemplate({ icon, name, desc, gradient, tags, coming }) {
        const comingBadge = coming ? `<span class="coming-soon-badge">即将推出</span>` : '';
        return `
          <div class="char-card divination-template" onclick="UI.toast('${name} 即将推出，敬请期待 ✨')">
            <div class="char-cover" style="background:${gradient}">
              <div class="divination-cover-icon">${icon}</div>
              <span class="type-badge divination">🔮 占卜</span>
              ${comingBadge}
            </div>
            <div class="char-info" style="padding:10px 12px 12px">
              <div class="char-name">${name}</div>
              <div class="char-bio">${desc}</div>
              <div class="char-tags" style="margin-top:8px">
                ${tags.map(t => `<span class="char-tag divination-tag">${t}</span>`).join('')}
              </div>
            </div>
          </div>
        `;
      }

      // ── 渲染可折叠分区（手风琴样式）────────────────────────────────
      // defaultOpen: 是否默认展开（对话陪伴默认展开，其他默认收起）
      function renderCollapsibleSection(key, items, extraCards = '', defaultOpen = false) {
        const meta = SECTION_META[key];
        const count = items.length + (extraCards ? 1 : 0); // 估算显示数量
        const realCount = items.length;
        const openClass = defaultOpen ? 'open' : '';
        const arrowChar = defaultOpen ? '▲' : '▼';
        const cardsHtml = items.map(renderCard).join('') + extraCards;
        
        // 空状态提示
        const emptyHtml = cardsHtml ? '' : `
          <div style="padding: 32px 20px; text-align: center; color: var(--muted); font-size: 14px;">
            <div style="font-size: 32px; margin-bottom: 12px; opacity: 0.5;">${meta.icon}</div>
            <div>暂无${meta.title}角色</div>
            <div style="font-size: 12px; margin-top: 6px; opacity: 0.7;">敬请期待后续更新</div>
          </div>
        `;

        return `
          <div class="square-accordion">
            <!-- 可点击的分区标题行 -->
            <div
              id="section-header-${key}"
              class="accordion-header ${openClass ? '' : 'collapsed'}"
              onclick="toggleSection('${key}')"
              style="--accent:${meta.accentColor};--gradient:${meta.gradient}"
            >
              <div class="accordion-header-left">
                <span class="accordion-icon">${meta.icon}</span>
                <div class="accordion-title-block">
                  <span class="accordion-title">${meta.title}</span>
                  <span class="accordion-desc">${meta.desc}</span>
                </div>
              </div>
              <div class="accordion-header-right">
                <span class="accordion-count">${realCount} 个</span>
                <span id="section-arrow-${key}" class="accordion-arrow">${arrowChar}</span>
              </div>
            </div>

            <!-- 可折叠的卡片区域 -->
            <div id="section-body-${key}" class="accordion-body ${openClass}">
              <div class="accordion-cards-grid">
                ${cardsHtml || emptyHtml}
              </div>
            </div>
          </div>
        `;
      }

      // 占卜分区：从模板卡渲染（暂无真实角色）
      const divinationCards = DIVINATION_TEMPLATES.map(t => renderDivinationTemplate(t)).join('');
      const divinationExtraOrReal =
        groups.divination.length > 0
          ? groups.divination.map(renderCard).join('')  // 将来有真实占卜角色时从这里取
          : divinationCards;

      // 拼装四个分区，全部默认收起
      grid.classList.remove('single-section'); // 多分区模式不需要此 class
      grid.innerHTML =
        renderCollapsibleSection('intimate',   groups.intimate,   '', false) +
        renderCollapsibleSection('scenario',   groups.scenario,   '', false) +
        renderCollapsibleSection('world',      groups.world,      '', false) +
        renderCollapsibleSection('divination', [], divinationExtraOrReal, false);
    }

    document.addEventListener('DOMContentLoaded', () => {
      const input = document.getElementById('chat-input');
      if (!input) return;

      // 输入框高度自适应（使用 requestAnimationFrame 优化性能）
      let rafId = null;
      input.addEventListener('input', () => {
        if (rafId) cancelAnimationFrame(rafId);
        rafId = requestAnimationFrame(() => {
          input.style.height = 'auto';
          input.style.height = Math.min(input.scrollHeight, 120) + 'px';
        });
      });

      // 键盘发送支持
      input.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          Chat.send();
        }
      });

      // iOS 键盘适配优化
      const chatPage = document.getElementById('page-chat');
      const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
      
      function onViewportResize() {
        if (!window.visualViewport) return;
        const vvh = window.visualViewport.height;
        const diff = window.innerHeight - vvh;
        
        if (chatPage) {
          // iOS 键盘弹出时调整 padding
          if (diff > 100) {
            chatPage.style.paddingBottom = `${diff + 20}px`;
            // 滚动到底部
            const box = document.getElementById('chat-messages');
            if (box) {
              requestAnimationFrame(() => {
                box.scrollTop = box.scrollHeight;
              });
            }
          } else {
            chatPage.style.paddingBottom = '';
          }
        }
      }

      if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', onViewportResize, { passive: true });
      }

      // 聚焦时滚动优化（iOS 需要延迟）
      input.addEventListener('focus', () => {
        if (isIOS) {
          setTimeout(() => {
            const box = document.getElementById('chat-messages');
            if (box) box.scrollTop = box.scrollHeight;
            // 确保输入框可见
            input.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          }, 300);
        }
      });

      // 防止 iOS 双击缩放
      let lastTouchEnd = 0;
      document.addEventListener('touchend', (e) => {
        const now = Date.now();
        if (now - lastTouchEnd <= 300) {
          e.preventDefault();
        }
        lastTouchEnd = now;
      }, { passive: false });
    });

    App.init();
