 const Chat = (() => {
  let currentChar = null;
  let isSending = false;
  let history = [];
  let _streamController = null;
  let _batchContainer = null;
  let _autoScroll = true;

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
    initSmartScroll();
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

   function appendHeaderSign(signEl, text = '') {
    signEl.innerHTML = '';
    const onlineDot = document.createElement('span');
    onlineDot.className = 'online-dot';
    signEl.appendChild(onlineDot);
    signEl.appendChild(document.createTextNode(text));
    return signEl;
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
     const signEl = document.getElementById('chat-sign');
    appendHeaderSign(signEl, char.sign || char.subtitle || '');
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

   function appendDividerNode(text, container = document.getElementById('chat-messages')) {
    const node = document.createElement('div');
    node.className = 'date-divider';
    node.textContent = text;
    container.appendChild(node);
    return node;
  }

  function appendDateDivider() {
    return appendDividerNode(formatDate(new Date()));
  }

  function appendLoadingHint(text) {
    return appendDividerNode(text);
  }

   function fillErrorBubble(bubble, text, row, retryText = null) {
   bubble.innerHTML = `⚠ ${escapeHtml(text)}`;
   if (!retryText) return bubble;
   const btn = createRetryButton(row, retryText);
   bubble.appendChild(document.createElement('br'));
   bubble.appendChild(btn);
   return bubble;
 }

 function appendMsg(role, text, createdAt = null, retryText = null, messageId = null) {
  const normalizedRole = role === 'ai' ? 'assistant' : role;
  const isError = normalizedRole === 'error';
  const container = _batchContainer || document.getElementById('chat-messages');
  const msgTime = createdAt ? new Date(createdAt).getTime() : Date.now();

  if (shouldShowTime(msgTime)) {
    appendMessageTime(container, createdAt ? new Date(createdAt) : new Date());
  }

  const row = createMessageRow((normalizedRole === 'assistant' || isError) ? 'ai' : normalizedRole, messageId);
  const isAi = normalizedRole === 'assistant';

  if (isAi && !isError) {
    appendRowAvatar(row, 'char', currentChar);
  }

  const bubble = createMessageBubble(isError ? 'error-bubble' : (normalizedRole === 'assistant' ? 'ai' : normalizedRole));
   if (isError) {
     fillErrorBubble(bubble, text, row, retryText);
     appendPlainBubble(row, bubble);
   } else {
    renderMessageBubble(bubble, text, normalizedRole === 'assistant');
    bindCopyHandlers(bubble, () => text);
    appendBubbleContent(row, bubble, isAi, messageId);
   }

 if (!isAi) {
   appendRowAvatar(row, 'user');
 }

 container.appendChild(row);
  _lastMsgTimestamp = msgTime;
 if (!_batchContainer) scrollToBottom();
  return row;
}

 function createRetryButton(row, retryText) {
   const btn = document.createElement('div');
   btn.className = 'retry-btn';
   btn.textContent = '🔄 重新发送';
   btn.addEventListener('click', () => {
     retryMessage(row, retryText);
   });
   return btn;
 }

 function retryMessage(row, retryText) {
   row.remove();
   const input = document.getElementById('chat-input');
   input.value = retryText;
   send();
   return input;
 }

 function assignMessageId(target, messageId = null) {
   if (target && messageId) target.dataset.messageId = messageId;
   return target;
 }

 function createAssistantHistoryEntry(content, messageId = null, createdAt = new Date().toISOString()) {
   return {
     role: 'assistant',
     content,
     created_at: createdAt,
     ...(messageId ? { message_id: messageId } : {}),
   };
 }

 function createMessageRow(roleClass, messageId = null) {
   const row = document.createElement('div');
   row.className = `msg-row ${roleClass}`;
   assignMessageId(row, messageId);
   return row;
 }

 function appendRowAvatar(row, type, charData = null) {
   const avatarEl = createMsgAvatar(type, charData);
   if (avatarEl) row.appendChild(avatarEl);
   return avatarEl;
 }

 function createMessageBubble(roleClass, text = '') {
   const bubble = document.createElement('div');
   bubble.className = `msg-bubble ${roleClass}`;
   bubble.textContent = text;
   return bubble;
 }

 function renderMessageBubble(bubbleEl, text, isAssistant = false) {
   renderTextWithLineBreaks(bubbleEl, text, isAssistant);
   return bubbleEl;
 }

 function appendPlainBubble(row, bubble) {
   row.appendChild(bubble);
   return bubble;
 }

 function appendAssistantBubble(row, bubble, actionBtns = null) {
  appendMessageBody(row, bubble, actionBtns);
  return bubble;
}

function createAssistantActionButtons(row = null, bubble = null, messageId = null, hiddenActions = false) {
  const actionBtns = createMessageActionButtons(hiddenActions);
  if (messageId) bindMessageActionButtons(actionBtns, row, bubble, messageId);
  return actionBtns;
}

function mountAssistantBubble(row, bubble, messageId = null) {
  const actionBtns = messageId ? createAssistantActionButtons(row, bubble, messageId) : null;
  appendAssistantBubble(row, bubble, actionBtns);
  return actionBtns;
}

function appendBubbleContent(row, bubble, isAi, messageId) {
  if (isAi) {
    mountAssistantBubble(row, bubble, messageId);
    return;
  }
  appendPlainBubble(row, bubble);
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

   function normalizeRenderedText(text) {
    return String(text).replace(/\n{2,}/g, '\n').trim();
  }

  function appendTextLines(el, lines) {
    lines.forEach((line, i) => {
      el.appendChild(document.createTextNode(line));
      if (i < lines.length - 1) el.appendChild(document.createElement('br'));
    });
    return el;
  }

  function resolveDisplayText(text, isAssistant = false) {
    if (!isAssistant) return text;
    const { cleanText, statusRaw } = CharStatusPanel.stripStatusBlock(text);
    if (statusRaw !== null) {
      CharStatusPanel.render(statusRaw);
    }
    return cleanText;
  }

  function renderTextWithLineBreaks(el, text, isAssistant = false) {
    el.innerHTML = '';
    const displayText = resolveDisplayText(text, isAssistant);
    const cleaned = normalizeRenderedText(displayText);
    const lines = cleaned.split('\n');
    appendTextLines(el, lines);
  }

   function flashElementClass(el, className, delay = 1800) {
    if (!el) return null;
    el.classList.add(className);
    setTimeout(() => el.classList.remove(className), delay);
    return el;
  }

  function showCopyToast() {
    const toast = document.getElementById('copy-toast');
    flashElementClass(toast, 'show');
  }

   function fillTypingBubble(bubble) {
    bubble.innerHTML = `
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
    `;
    return bubble;
  }

  function showTyping() {
    const box = document.getElementById('chat-messages');
    const row = createMessageRow('ai');
    row.id = 'typing-row';
    appendRowAvatar(row, 'char', currentChar);
    const bubble = fillTypingBubble(createMessageBubble('typing'));
    row.appendChild(bubble);
    box.appendChild(row);
    scrollToBottom();
  }

   function createStreamState() {
    return {
      bubbleEl: null,
      actionBtnsEl: null,
      streamRowEl: null,
      aiText: '',
    };
  }

  function handleStreamChunk(streamState, chunk) {
    if (!chunk) return;
    renderStreamReply(streamState, streamState.aiText + chunk);
  }

  function finalizeStreamReply(streamState, replyText) {
    ensureStreamReplyRow(streamState, replyText || '');
    renderStreamReply(streamState, replyText || streamState.aiText);
  }

  function appendLocalConversation(userText, assistantText, messageId = null) {
    const createdAt = new Date().toISOString();
    history.push({ role: 'user', content: userText, created_at: createdAt });
    history.push(createAssistantHistoryEntry(assistantText, messageId, createdAt));
  }

  function hideStreamActionButtons(streamState) {
    if (streamState.actionBtnsEl) streamState.actionBtnsEl.style.display = 'none';
  }

  function bindPersistedStreamActions(streamState, messageId) {
    if (!messageId) {
      hideStreamActionButtons(streamState);
      return;
    }
    assignMessageId(streamState.streamRowEl, messageId);
    bindMessageActionButtons(streamState.actionBtnsEl, streamState.streamRowEl, streamState.bubbleEl, messageId);
  }

  function handleStreamError(streamState, payload, fallbackMessage = '网络波动，请稍后再试') {
    cleanupStreamState(streamState);
    UI.toast(payload?.message || fallbackMessage, 'warn', 3000);
  }

  function setButtonLoading(buttonEl, disabled, loading = false) {
    if (!buttonEl) return;
    buttonEl.disabled = disabled;
    buttonEl.classList.toggle('loading', loading);
  }

  function setActionButtonsVisible(actionBtnsEl, visible) {
    if (!actionBtnsEl) return;
    actionBtnsEl.style.display = visible ? '' : 'none';
  }

  function getMessageActionButtons(rowEl) {
    return {
      regenerate: rowEl?.querySelector('.regenerate-btn') || null,
      continue: rowEl?.querySelector('.continue-btn') || null,
      actions: rowEl?.querySelector('.msg-action-btns') || null,
    };
  }

  function beginMessageAction(rowEl, { loading = null, showTypingBubble = false, hideActions = false } = {}) {
    const buttons = getMessageActionButtons(rowEl);
    setSending(true);
    if (showTypingBubble) showTyping();
    abortStream();
    _streamController = new AbortController();

    if (loading === 'regenerate') {
      setButtonLoading(buttons.regenerate, true, true);
      setButtonLoading(buttons.continue, true);
    } else if (loading === 'continue') {
      setButtonLoading(buttons.regenerate, true);
      setButtonLoading(buttons.continue, true, true);
    }

    if (hideActions) {
      setActionButtonsVisible(buttons.actions, false);
    }

    return buttons;
  }

  function completeMessageAction(buttons = {}, { loading = null, restoreActions = false } = {}) {
    if (loading === 'regenerate') {
      setButtonLoading(buttons.regenerate, false, false);
      setButtonLoading(buttons.continue, false);
    } else if (loading === 'continue') {
      setButtonLoading(buttons.regenerate, false);
      setButtonLoading(buttons.continue, false, false);
    }

    if (restoreActions) {
      setActionButtonsVisible(buttons.actions, true);
    }

    removeTyping();
    setSending(false);
    return buttons;
  }

  function resolveContinuationResult(originalText, appendedText, payload, messageId) {
    const finalAppended = payload?.appended_text || appendedText;
    const nextMessageId = payload?.message_id || messageId;
    return {
      finalAppended,
      nextMessageId,
      fullText: `${originalText || ''}${finalAppended}`,
    };
  }

  function cleanupContinuationFailure(newRowEl, originalButtons, message) {
    removeTyping();
    removeRowIfPresent(newRowEl);
    UI.toast(message, 'warn', 3000);
    setActionButtonsVisible(originalButtons?.actions, true);
  }

  function syncCharacterState(payload) {
    if (payload?.character_state) {
      renderStateBar(payload.character_state);
    }
  }

  function removeRowIfPresent(rowEl) {
    if (rowEl?.parentNode) rowEl.remove();
  }

  function removeElementById(elementId) {
    const el = document.getElementById(elementId);
    removeRowIfPresent(el);
    return el;
  }

  function cleanupStreamState(state) {
    removeTyping();
    removeRowIfPresent(state?.streamRowEl);
    return resetStreamState(state);
  }

  function createAiMessageElements(hiddenActions = false) {
    const row = createMessageRow('ai');
    appendRowAvatar(row, 'char', currentChar);
    const bubble = createMessageBubble('ai');
    const actionBtns = createAssistantActionButtons(row, bubble, null, hiddenActions);
    appendAssistantBubble(row, bubble, actionBtns);
    return { row, bubble, actionBtns };
  }

  function insertMessageRow(container, row, nextSibling = null) {
    if (nextSibling) {
      container.insertBefore(row, nextSibling);
      return row;
    }
    container.appendChild(row);
    return row;
  }

  function placeAiMessageRow(container, row, nextSibling = null, shouldScroll = false) {
    insertMessageRow(container, row, nextSibling);
    if (shouldScroll) scrollToBottom();
    return row;
  }

  function appendMessageTimeIfNeeded(container, timestamp, date = new Date()) {
    if (shouldShowTime(timestamp)) {
      appendMessageTime(container, date);
    }
    return container;
  }

  function configureAiMessageRow(row, bubble, messageId = null, getText = null) {
    assignMessageId(row, messageId);
    if (getText) bindCopyHandlers(bubble, getText);
    return row;
  }

  function initializeAiMessageRow(container, timestamp, {
    nextSibling = null,
    hiddenActions = false,
    shouldScroll = false,
    messageId = null,
    getText = null,
  } = {}) {
    appendMessageTimeIfNeeded(container, timestamp, new Date());
    const aiMessageRow = createAiMessageElements(hiddenActions);
    configureAiMessageRow(aiMessageRow.row, aiMessageRow.bubble, messageId, getText);
    placeAiMessageRow(container, aiMessageRow.row, nextSibling, shouldScroll);
    return aiMessageRow;
  }

  function createContinuationMessageRow(sourceRowEl, messageId, getText) {
    const box = document.getElementById('chat-messages');
    const contMsgTime = Date.now();

    const { row, bubble, actionBtns } = initializeAiMessageRow(box, contMsgTime, {
      nextSibling: sourceRowEl.nextSibling,
      messageId,
      getText,
    });

    _lastMsgTimestamp = contMsgTime;

    return { row, bubble, actionBtns };
  }

  function finalizeAssistantMessageUpdate(messageId, content, payload, fallbackMessageId = messageId) {
    updateAssistantHistoryMessage(messageId, content, payload?.message_id || fallbackMessageId);
    syncCharacterState(payload);
  }

  function removeTyping() {
    removeElementById('typing-row');
  }

   function createStreamRow() {
   const box = document.getElementById('chat-messages');
   const msgTime = Date.now();

   const streamRow = initializeAiMessageRow(box, msgTime, {
     hiddenActions: true,
     shouldScroll: true,
   });
   _lastMsgTimestamp = msgTime;
   
   return streamRow;
 }

  function assignStreamState(state, streamRow, initialText = '') {
    state.bubbleEl = streamRow.bubble;
    state.actionBtnsEl = streamRow.actionBtns;
    state.streamRowEl = streamRow.row;
    state.aiText = initialText;
    return state;
  }

  function attachStreamRow(state, streamRow, initialText = '') {
    assignStreamState(state, streamRow, initialText);
    if (initialText) {
      renderMessageBubble(state.bubbleEl, state.aiText, true);
    }
    return state;
  }

  function ensureStreamState(state, initialText = '') {
    if (state.bubbleEl) return state;
    removeTyping();
    return attachStreamRow(state, createStreamRow(), initialText);
  }

  function resetStreamState(state) {
    state.bubbleEl = null;
    state.actionBtnsEl = null;
    state.streamRowEl = null;
    state.aiText = '';
    return state;
  }


  function ensureStreamReplyRow(state, initialText = '') {
    return ensureStreamState(state, initialText);
  }

  function renderStreamReply(state, nextText) {
    ensureStreamState(state);
    state.aiText = nextText;
    renderMessageBubble(state.bubbleEl, state.aiText, true);
    scrollToBottom();
  }

  function discardStreamReply(state) {
    cleanupStreamState(state);
  }

  function updateAssistantHistoryMessage(messageId, content, nextMessageId = messageId) {
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
        content,
        created_at: new Date().toISOString(),
        message_id: nextMessageId || messageId,
      };
    }
  }

  function bindMessageActionButtons(actionBtnsEl, rowEl, bubbleEl, messageId) {
    if (!actionBtnsEl) return;
    if (!messageId) {
      actionBtnsEl.style.display = 'none';
      return;
    }
    actionBtnsEl.style.opacity = '';
    rowEl.dataset.messageId = messageId;
    actionBtnsEl.querySelector('.regenerate-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      regenerateMessage(messageId, rowEl, bubbleEl);
    });
    actionBtnsEl.querySelector('.continue-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      continueMessage(messageId, rowEl, bubbleEl);
    });
  }

  function copyMessageText(getText) {
    return navigator.clipboard.writeText(getText()).then(() => {
      showCopyToast();
    });
  }

  function bindCopyHandlers(bubbleEl, getText) {
    const doCopy = () => copyMessageText(getText);
    bubbleEl.addEventListener('dblclick', doCopy);
    let pressTimer;
    bubbleEl.addEventListener('touchstart', () => { pressTimer = setTimeout(doCopy, 600); }, { passive: true });
    bubbleEl.addEventListener('touchend', () => clearTimeout(pressTimer), { passive: true });
    bubbleEl.addEventListener('touchmove', () => clearTimeout(pressTimer), { passive: true });
  }

  function createMessageActionButtons(hidden = false) {
    const actionBtns = document.createElement('div');
    actionBtns.className = 'msg-action-btns';
    actionBtns.innerHTML = `
      <button class="msg-action-btn regenerate-btn" title="重新生成">↻</button>
      <button class="msg-action-btn continue-btn" title="继续生成">▶</button>
    `;
    if (hidden) actionBtns.style.opacity = '0';
    return actionBtns;
  }

  function appendMessageBody(rowEl, bubbleEl, actionBtnsEl = null) {
    const body = document.createElement('div');
    body.className = 'msg-body';
    body.appendChild(bubbleEl);
    if (actionBtnsEl) body.appendChild(actionBtnsEl);
    rowEl.appendChild(body);
    return body;
  }

  function appendMessageTime(container, date) {
    const timeEl = document.createElement('div');
    timeEl.className = 'msg-time';
    timeEl.textContent = formatSmartTime(date);
    container.appendChild(timeEl);
    return timeEl;
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

   function buildGuestStreamHandlers(streamState, userText) {
    return {
      onChunk(chunk) {
        handleStreamChunk(streamState, chunk);
      },
      onDone(payload) {
        finalizeStreamReply(streamState, payload?.reply);
        appendLocalConversation(userText, streamState.aiText);
        hideStreamActionButtons(streamState);
      },
      onError(payload) {
        handleStreamError(streamState, payload);
      },
    };
  }

  function buildLoggedInStreamHandlers(streamState, userText) {
    return {
      onChunk(chunk) {
        handleStreamChunk(streamState, chunk);
      },
      onDone(payload) {
        finalizeStreamReply(streamState, payload?.reply);

        const msgId = payload?.message_id || null;
        appendLocalConversation(userText, streamState.aiText, msgId);
        syncCharacterState(payload);
        bindPersistedStreamActions(streamState, msgId);
      },
      onError(payload) {
        handleStreamError(streamState, payload);
      },
    };
  }

  async function handleSendFailure(err, userText) {
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
    appendMsg('error', `发送失败：${err.message}`, null, userText);
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

    const streamState = createStreamState();

     try {
      if (!Auth.isLoggedIn()) {
        const guestHistory = history.slice(-8).map(m => ({ role: m.role, content: m.content }));
        await API.guestStreamMessage(
          {
            character_id: currentChar.id,
            message: text,
            guest_history: guestHistory,
          },
          buildGuestStreamHandlers(streamState, text),
          _streamController.signal
        );
        await refreshGuestQuota();
      } else {
        await API.streamMessage(
          {
            character_id: currentChar.id,
            message: text,
          },
          buildLoggedInStreamHandlers(streamState, text),
          _streamController.signal
        );
      }
    } catch (err) {
      await handleSendFailure(err, text);
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

   function scrollToBottom(force = false) {
     if (!force && !_autoScroll) return;
     const box = document.getElementById('chat-messages');
     box.scrollTop = box.scrollHeight;
   }

   function initSmartScroll() {
     const box = document.getElementById('chat-messages');
     if (!box) return;
     const THRESHOLD = 120;
     box.addEventListener('scroll', () => {
       const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < THRESHOLD;
       _autoScroll = atBottom;
     }, { passive: true });
   }

   /* ── Regenerate / Continue 功能 ─────────────────────────── */
   
   async function regenerateMessage(messageId, rowEl, bubbleEl) {
   if (isSending || !Auth.isLoggedIn()) return;

   const buttons = beginMessageAction(rowEl, { loading: 'regenerate' });
   let aiText = '';

   try {
     await API.regenerateMessage(
       { message_id: messageId },
       {
         onChunk(chunk) {
           if (!chunk) return;
           aiText += chunk;
           renderMessageBubble(bubbleEl, aiText, true);
           scrollToBottom();
         },
         onDone(payload) {
          aiText = payload?.reply || aiText;
          renderMessageBubble(bubbleEl, aiText, true);
          finalizeAssistantMessageUpdate(messageId, aiText, payload);
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
      completeMessageAction(buttons, { loading: 'regenerate' });
    }
  }

   async function continueMessage(messageId, rowEl, bubbleEl) {
  if (isSending || !Auth.isLoggedIn()) return;

  const buttons = beginMessageAction(rowEl, {
    loading: 'continue',
    showTypingBubble: true,
    hideActions: true,
  });
  let appendedText = '';
  let newBubbleEl = null;
  let newRowEl = null;
  let newActionBtnsEl = null;

  try {
    await API.continueMessage(
      { message_id: messageId },
      {
        onChunk(chunk) {
          if (!chunk) return;
          removeTyping();
          appendedText += chunk;

          if (!newBubbleEl) {
            const continuationRow = createContinuationMessageRow(rowEl, messageId, () => appendedText);
            newRowEl = continuationRow.row;
            newBubbleEl = continuationRow.bubble;
            newActionBtnsEl = continuationRow.actionBtns;
          }

          renderMessageBubble(newBubbleEl, appendedText, true);
          scrollToBottom();
        },
        onDone(payload) {
          const { finalAppended, nextMessageId, fullText } = resolveContinuationResult(
            bubbleEl.textContent,
            appendedText,
            payload,
            messageId
          );
          if (newBubbleEl) renderMessageBubble(newBubbleEl, finalAppended, true);

          finalizeAssistantMessageUpdate(messageId, fullText, payload, nextMessageId);
          bindMessageActionButtons(newActionBtnsEl, newRowEl, newBubbleEl, nextMessageId);
          setActionButtonsVisible(buttons.actions, false);
        },
        onError(payload) {
          cleanupContinuationFailure(newRowEl, buttons, payload?.message || '继续生成失败');
        },
      },
      _streamController.signal
    );
  } catch (err) {
    removeTyping();
    removeRowIfPresent(newRowEl);
    UI.toast(`继续生成失败：${err.message}`, 'error');
    setActionButtonsVisible(buttons.actions, true);
  } finally {
    completeMessageAction(buttons, { loading: 'continue' });
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

