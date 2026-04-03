 const Chat = (() => {
  let currentChar = null;
  let isSending = false;
  let history = [];
  let _streamController = null;
  let _batchContainer = null;

  function abortStream() {
    if (_streamController) {
      _streamController.abort();
      _streamController = null;
    }
  }

  let guestQuota = null;

   /** 渲染游客体验提示（仅游客可见）。 */
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
     _lastMsgTimestamp = 0;
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

  let _lastMsgTimestamp = 0;

   function shouldShowTime(timestamp) {
     if (!_lastMsgTimestamp) return true;
     const gap = Math.abs(timestamp - _lastMsgTimestamp);
     return gap >= 5 * 60 * 1000;
   }

   function formatSmartTime(date) {
     const now = new Date();
     const d = new Date(date);
     const h = String(d.getHours()).padStart(2, '0');
     const m = String(d.getMinutes()).padStart(2, '0');
     const timeStr = `${h}:${m}`;
     if (d.toDateString() === now.toDateString()) return timeStr;
     const yesterday = new Date(now);
     yesterday.setDate(yesterday.getDate() - 1);
     if (d.toDateString() === yesterday.toDateString()) return `昨天 ${timeStr}`;
     return `${d.getMonth() + 1}月${d.getDate()}日 ${timeStr}`;
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

   function appendMsg(role, text, createdAt = null, retryText = null, messageId = null) {
    const normalizedRole = role === 'ai' ? 'assistant' : role;
    const isError = normalizedRole === 'error';
    const container = _batchContainer || document.getElementById('chat-messages');
    const msgTime = createdAt ? new Date(createdAt).getTime() : Date.now();

    if (shouldShowTime(msgTime)) {
      const timeEl = document.createElement('div');
      timeEl.className = 'msg-time';
      timeEl.textContent = formatSmartTime(createdAt ? new Date(createdAt) : new Date());
      container.appendChild(timeEl);
    }

    const row = document.createElement('div');
    row.className = `msg-row ${(normalizedRole === 'assistant' || isError) ? 'ai' : normalizedRole}`;

    const isAi = normalizedRole === 'assistant';

    if (isAi && !isError) {
      const avatarEl = createMsgAvatar('char', currentChar);
      if (avatarEl) row.appendChild(avatarEl);
    }

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

       // 为 AI 消息添加 Regenerate / Continue 操作按钮
       if (normalizedRole === 'assistant' && messageId) {
         const actionBtns = document.createElement('div');
         actionBtns.className = 'msg-action-btns';
         actionBtns.innerHTML = `
           <button class="msg-action-btn regenerate-btn" title="重新生成" data-message-id="${messageId}">↻</button>
           <button class="msg-action-btn continue-btn" title="继续生成" data-message-id="${messageId}">▶</button>
         `;
         
         // 绑定事件
         actionBtns.querySelector('.regenerate-btn').addEventListener('click', (e) => {
           e.stopPropagation();
           regenerateMessage(messageId, row, bubble);
         });
         actionBtns.querySelector('.continue-btn').addEventListener('click', (e) => {
           e.stopPropagation();
           continueMessage(messageId, row, bubble);
         });

         row.appendChild(actionBtns);
        row.dataset.messageId = messageId;
      }
     }

     row.appendChild(bubble);

   if (!isAi) {
     const avatarEl = createMsgAvatar('user');
     if (avatarEl) row.appendChild(avatarEl);
   }

   container.appendChild(row);
    _lastMsgTimestamp = msgTime;
   if (!_batchContainer) scrollToBottom();
    return row;
  }

  function createMsgAvatar(type, charData = null) {
    const el = document.createElement('div');
    el.className = 'msg-avatar';
    const SERVER_ORIGIN = typeof API_BASE !== 'undefined' ? API_BASE.replace(/\/api$/, '') : '';

    if (type === 'char' && charData) {
      const rawImg = charData.avatarImg || charData.coverImg || null;
      if (rawImg) {
        const imgSrc = rawImg.startsWith('/') ? SERVER_ORIGIN + rawImg : rawImg;
        const img = document.createElement('img');
        img.src = imgSrc;
        img.alt = charData.display_name || charData.name || '';
        img.onerror = () => {
          el.textContent = (charData.abbr || (charData.display_name || charData.name || '角')[0]);
          el.style.background = charData.color || 'linear-gradient(135deg,#8a72ff,#ff7eb6)';
        };
        el.appendChild(img);
        return el;
      }
      el.textContent = charData.abbr || (charData.display_name || charData.name || '角')[0];
      el.style.background = charData.color || 'linear-gradient(135deg,#8a72ff,#ff7eb6)';
      return el;
    }

    if (type === 'user') {
      const user = Auth.getUser && Auth.getUser();
      const avatarUrl = user?.avatar_url;
      if (avatarUrl) {
        const img = document.createElement('img');
        img.src = avatarUrl.startsWith('/') ? SERVER_ORIGIN + avatarUrl : avatarUrl;
        img.alt = user?.nickname || '你';
        img.onerror = () => { el.textContent = (user?.nickname || '你')[0]; };
        el.appendChild(img);
        return el;
      }
      el.textContent = (user?.nickname || '你')[0].toUpperCase();
      el.style.background = 'linear-gradient(135deg, #667eea, #764ba2)';
      return el;
    }

    return null;
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
    const avatarEl = createMsgAvatar('char', currentChar);
    if (avatarEl) row.appendChild(avatarEl);
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
    const msgTime = Date.now();

    if (shouldShowTime(msgTime)) {
      const timeEl = document.createElement('div');
      timeEl.className = 'msg-time';
      timeEl.textContent = formatSmartTime(new Date());
      box.appendChild(timeEl);
    }

    const row = document.createElement('div');
    row.className = 'msg-row ai';

    const avatarEl = createMsgAvatar('char', currentChar);
    if (avatarEl) row.appendChild(avatarEl);

    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble ai';
    bubble.textContent = '';

    // 预创建操作按钮容器（初始隐藏，onDone 时显示并绑定事件）
    const actionBtns = document.createElement('div');
    actionBtns.className = 'msg-action-btns';
    actionBtns.innerHTML = `
      <button class="msg-action-btn regenerate-btn" title="重新生成">↻</button>
      <button class="msg-action-btn continue-btn" title="继续生成">▶</button>
    `;
    actionBtns.style.opacity = '0';

    row.appendChild(bubble);
    row.appendChild(actionBtns);
    box.appendChild(row);
    _lastMsgTimestamp = msgTime;
    scrollToBottom();
    
    return { row, bubble, actionBtns };
  }

   function renderHistory(messages) {
     const box = document.getElementById('chat-messages');
     box.innerHTML = '';
     _lastMsgTimestamp = 0;
     appendDateDivider();
     _batchContainer = document.createDocumentFragment();
     while (box.firstChild) {
       _batchContainer.appendChild(box.firstChild);
     }
     messages.forEach(item => appendMsg(item.role, item.content, item.created_at));
     box.appendChild(_batchContainer);
     _batchContainer = null;
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
    abortStream();
    _streamController = new AbortController();
    // 移动端发送后不立即 focus（避免键盘弹起遮盖内容），桌面端保持 focus
     if (window.innerWidth > 500) input.focus();

     let bubbleEl = null;
     let actionBtnsEl = null;
     let streamRowEl = null;
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
                 const sr = createStreamRow();
                 bubbleEl = sr.bubble;
                 actionBtnsEl = sr.actionBtns;
                 streamRowEl = sr.row;
               }
               aiText += chunk;
               renderTextWithLineBreaks(bubbleEl, aiText, true);
               scrollToBottom();
             },
             onDone(payload) {
               if (!bubbleEl) {
                 removeTyping();
                 const sr = createStreamRow();
                 bubbleEl = sr.bubble;
                 actionBtnsEl = sr.actionBtns;
                 streamRowEl = sr.row;
                 aiText = payload?.reply || '';
               }
               aiText = payload?.reply || aiText;
               renderTextWithLineBreaks(bubbleEl, aiText, true);
               // 游客：存本地 history（不存服务端）
               history.push({ role: 'user', content: text, created_at: new Date().toISOString() });
               history.push({ role: 'assistant', content: aiText, created_at: new Date().toISOString() });
               // 游客模式：隐藏按钮（因为没有 message_id）
               if (actionBtnsEl) actionBtnsEl.style.display = 'none';
             },
             // AI 调用失败时，后端不发 chunk/done，只发 error 事件
             onError(payload) {
               removeTyping();
               // 删除整个 AI 消息行（如果已创建的话）
               if (streamRowEl && streamRowEl.parentNode) {
                 streamRowEl.remove();
               }
               bubbleEl = null;
               actionBtnsEl = null;
               streamRowEl = null;
               UI.toast(payload?.message || '网络波动，请稍后再试', 'warn', 3000);
             },
           },
           _streamController.signal
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
                 const sr = createStreamRow();
                 bubbleEl = sr.bubble;
                 actionBtnsEl = sr.actionBtns;
                 streamRowEl = sr.row;
               }
               aiText += chunk;
               renderTextWithLineBreaks(bubbleEl, aiText, true);
               scrollToBottom();
             },
             onDone(payload) {
              if (!bubbleEl) {
                removeTyping();
                const sr = createStreamRow();
                bubbleEl = sr.bubble;
                actionBtnsEl = sr.actionBtns;
                streamRowEl = sr.row;
                aiText = payload?.reply || '';
              }
              aiText = payload?.reply || aiText;
               renderTextWithLineBreaks(bubbleEl, aiText, true);
              
              const msgId = payload?.message_id || null;
              if (msgId) streamRowEl.dataset.messageId = msgId;
              
              history.push({ role: 'user', content: text, created_at: new Date().toISOString() });
               history.push({ role: 'assistant', content: aiText, created_at: new Date().toISOString(), message_id: msgId });
               // 如果 AI 输出里包含状态增量，后端已经更新 DB 并在 done 事件里返回最新状态
               if (payload?.character_state) {
                 renderStateBar(payload.character_state);
               }
               // 绑定 Regenerate / Continue 按钮事件
               if (actionBtnsEl && msgId) {
                 actionBtnsEl.style.opacity = '';
                 streamRowEl.dataset.messageId = msgId;
                 actionBtnsEl.querySelector('.regenerate-btn').addEventListener('click', (e) => {
                   e.stopPropagation();
                   regenerateMessage(msgId, streamRowEl, bubbleEl);
                 });
                 actionBtnsEl.querySelector('.continue-btn').addEventListener('click', (e) => {
                   e.stopPropagation();
                   continueMessage(msgId, streamRowEl, bubbleEl);
                 });
               } else if (actionBtnsEl) {
                 // 没有 message_id 时隐藏按钮
                 actionBtnsEl.style.display = 'none';
               }
             },
             // AI 调用失败时，后端不发 chunk/done，只发 error 事件
             onError(payload) {
               removeTyping();
               // 删除整个 AI 消息行（如果已创建的话）
               if (streamRowEl && streamRowEl.parentNode) {
                 streamRowEl.remove();
               }
               bubbleEl = null;
               actionBtnsEl = null;
               streamRowEl = null;
               UI.toast(payload?.message || '网络波动，请稍后再试', 'warn', 3000);
             },
           },
           _streamController.signal
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

   /* ── Regenerate / Continue 功能 ─────────────────────────── */
   
   async function regenerateMessage(messageId, rowEl, bubbleEl) {
    if (isSending || !Auth.isLoggedIn()) return;

    setSending(true);
    abortStream();
    _streamController = new AbortController();

    const regenBtn = rowEl.querySelector('.regenerate-btn');
    const contBtn = rowEl.querySelector('.continue-btn');
    if (regenBtn) { regenBtn.disabled = true; regenBtn.classList.add('loading'); }
    if (contBtn) contBtn.disabled = true;

    let aiText = '';

    try {
      await API.regenerateMessage(
        { message_id: messageId },
        {
          onChunk(chunk) {
            if (!chunk) return;
            aiText += chunk;
            renderTextWithLineBreaks(bubbleEl, aiText, true);
            scrollToBottom();
          },
          onDone(payload) {
           aiText = payload?.reply || aiText;
           renderTextWithLineBreaks(bubbleEl, aiText, true);

           let msgIdx = -1;
           for (let i = history.length - 1; i >= 0; i--) {
             if (history[i].message_id === messageId || (history[i].role === 'assistant' && !history[i].message_id)) {
               msgIdx = i;
               break;
             }
           }
           if (msgIdx !== -1) {
             history[msgIdx] = {
               ...history[msgIdx],
               content: aiText,
               created_at: new Date().toISOString(),
               message_id: payload?.message_id || messageId,
             };
           }

           if (payload?.character_state) {
             renderStateBar(payload.character_state);
           }
         },
          onError(payload) {
            UI.toast(payload?.message || '重新生成失败', 'warn', 3000);
          },
        },
        _streamController.signal
      );
     } catch (err) {
       UI.toast(`重新生成失败：${err.message}`, 'error');
     } finally {
       if (regenBtn) { regenBtn.disabled = false; regenBtn.classList.remove('loading'); }
       if (contBtn) contBtn.disabled = false;
       setSending(false);
     }
   }

   async function continueMessage(messageId, rowEl, bubbleEl) {
    if (isSending || !Auth.isLoggedIn()) return;

    setSending(true);
    showTyping();
    abortStream();
    _streamController = new AbortController();

    let appendedText = '';
    let newBubbleEl = null;
    let newRowEl = null;
    let newActionBtnsEl = null;

    const originalBtns = rowEl.querySelector('.msg-action-btns');
    if (originalBtns) originalBtns.style.display = 'none';

    try {
      await API.continueMessage(
        { message_id: messageId },
        {
          onChunk(chunk) {
            if (!chunk) return;
            removeTyping();
            appendedText += chunk;

            if (!newBubbleEl) {
              const box = document.getElementById('chat-messages');
              const contMsgTime = Date.now();

              if (shouldShowTime(contMsgTime)) {
                const timeEl = document.createElement('div');
                timeEl.className = 'msg-time';
                timeEl.textContent = formatSmartTime(new Date());
                box.appendChild(timeEl);
              }

              newRowEl = document.createElement('div');
              newRowEl.className = 'msg-row ai';
              newRowEl.dataset.messageId = messageId;

              const contAvatarEl = createMsgAvatar('char', currentChar);
              if (contAvatarEl) newRowEl.appendChild(contAvatarEl);

              newBubbleEl = document.createElement('div');
              newBubbleEl.className = 'msg-bubble ai';

              newActionBtnsEl = document.createElement('div');
              newActionBtnsEl.className = 'msg-action-btns';
              newActionBtnsEl.innerHTML = `
                <button class="msg-action-btn regenerate-btn" title="重新生成">↻</button>
                <button class="msg-action-btn continue-btn" title="继续生成">▶</button>
              `;

              const doCopy = () => { navigator.clipboard.writeText(appendedText).then(() => showCopyToast()); };
              newBubbleEl.addEventListener('dblclick', doCopy);
              let pressTimer;
              newBubbleEl.addEventListener('touchstart', () => { pressTimer = setTimeout(doCopy, 600); }, { passive: true });
              newBubbleEl.addEventListener('touchend', () => clearTimeout(pressTimer), { passive: true });
              newBubbleEl.addEventListener('touchmove', () => clearTimeout(pressTimer), { passive: true });

              newRowEl.appendChild(newBubbleEl);
              newRowEl.appendChild(newActionBtnsEl);

              const sibling = rowEl.nextSibling;
              if (sibling) {
                box.insertBefore(newRowEl, sibling);
              } else {
                box.appendChild(newRowEl);
              }
              _lastMsgTimestamp = contMsgTime;
            }

            renderTextWithLineBreaks(newBubbleEl, appendedText, true);
            scrollToBottom();
          },
          onDone(payload) {
            const finalAppended = payload?.appended_text || appendedText;
            if (newBubbleEl) renderTextWithLineBreaks(newBubbleEl, finalAppended, true);

            const fullText = (bubbleEl.textContent || '') + finalAppended;

            let msgIdx = -1;
            for (let i = history.length - 1; i >= 0; i--) {
              if (history[i].message_id === messageId || (history[i].role === 'assistant' && !history[i].message_id)) {
                msgIdx = i;
                break;
              }
            }
            if (msgIdx !== -1) {
              history[msgIdx] = {
                ...history[msgIdx],
                content: fullText,
                created_at: new Date().toISOString(),
                message_id: payload?.message_id || messageId,
              };
            }

            if (payload?.character_state) {
              renderStateBar(payload.character_state);
            }

            if (newActionBtnsEl && messageId) {
              newActionBtnsEl.style.opacity = '';
              newActionBtnsEl.querySelector('.regenerate-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                regenerateMessage(messageId, newRowEl, newBubbleEl);
              });
              newActionBtnsEl.querySelector('.continue-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                continueMessage(messageId, newRowEl, newBubbleEl);
              });
            } else if (newActionBtnsEl) {
              newActionBtnsEl.style.display = 'none';
            }

            if (originalBtns) originalBtns.style.display = 'none';
          },
          onError(payload) {
            removeTyping();
            if (newRowEl && newRowEl.parentNode) newRowEl.remove();
            UI.toast(payload?.message || '继续生成失败', 'warn', 3000);
            if (originalBtns) originalBtns.style.display = '';
          },
        },
        _streamController.signal
      );
    } catch (err) {
      removeTyping();
      if (newRowEl && newRowEl.parentNode) newRowEl.remove();
      UI.toast(`继续生成失败：${err.message}`, 'error');
      if (originalBtns) originalBtns.style.display = '';
    } finally {
      removeTyping();
      setSending(false);
    }
  }

   return {
     enterChat,
     send,
     regenerateMessage,
     continueMessage,
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

