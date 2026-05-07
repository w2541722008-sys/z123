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
         <span class="trial-status ${statusClass}">${escapeHtml(statusText)}</span>
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
  // 标签映射：对话陪伴 vs 剧情沙盒共用同一套枚举值，但展示语义不同
  const INTIMATE_PHASE_LABELS = {
    stranger: '陌生人', acquaintance: '普通朋友', friend: '好友', lover: '恋人',
  };
  const SCENARIO_PHASE_LABELS = {
    stranger: '初入', acquaintance: '探索', friend: '深入', lover: '终章',
  };
  const INTIMATE_MOOD_LABELS = {
    neutral: '平静', happy: '开心', warm: '温柔', melting: '心动',
    cold: '冷淡', angry: '生气', sad: '难过', shy: '害羞', surprised: '惊讶',
  };
  const SCENARIO_MOOD_LABELS = {
    neutral: '平静', happy: '振奋', warm: '安宁', melting: '沉浸',
    cold: '萧瑟', angry: '敌意', sad: '低落', shy: '警惕', surprised: '震惊',
  };
  const MOOD_CLASSES = Object.keys(INTIMATE_MOOD_LABELS);

  function _getLabels() {
    const ct = (currentChar && currentChar.card_type) || 'intimate';
    return ct === 'scenario'
      ? { phase: SCENARIO_PHASE_LABELS, mood: SCENARIO_MOOD_LABELS, affectionName: '沉浸度' }
      : { phase: INTIMATE_PHASE_LABELS, mood: INTIMATE_MOOD_LABELS, affectionName: '好感度' };
  }

  function _isStateBarHidden() {
    // 由角色卡配置的 show_bar 控制，默认显示
    // 优先从最新渲染的状态数据读取，否则从角色卡读取
    if (_lastState && _lastState.show_bar === false) return true;
    if (currentChar) {
      try {
        const rules = JSON.parse(currentChar.affection_rules_json || '{}');
        return rules.show_bar === false;
      } catch (_) {}
    }
    return false;
  }

  let _lastState = null;

  function renderStateBar(state) {
    const barEl = document.getElementById('chat-state-bar');
    if (!barEl || !state) return;

    _lastState = state;

    // 角色卡配置了隐藏状态栏 → 整栏不显示
    if (_isStateBarHidden()) {
      barEl.style.display = 'none';
      return;
    }

    const affection = Math.max(0, Math.min(100, state.affection || 0));
    const phase = state.story_phase || 'stranger';
    const mood = state.mood || 'neutral';
    const labels = _getLabels();

    // 标签文本（对话陪伴→好感度，剧情沙盒→沉浸度）
    const labelEl = document.getElementById('state-affection-label');
    if (labelEl) labelEl.textContent = labels.affectionName;

    // 好感度/沉浸度条
    const fill = document.getElementById('affection-bar-fill');
    if (fill) {
      fill.style.width = affection + '%';
      fill.classList.toggle('full', affection >= 100);
    }
    const valEl = document.getElementById('affection-value');
    if (valEl) valEl.textContent = affection;

    // 阶段 pill
    const phaseEl = document.getElementById('state-phase');
    if (phaseEl) phaseEl.textContent = labels.phase[phase] || phase;

    // 心情 pill（更新颜色 class）
    const moodEl = document.getElementById('state-mood');
    if (moodEl) {
      moodEl.textContent = labels.mood[mood] || mood;
      MOOD_CLASSES.forEach(m => moodEl.classList.remove('mood-' + m));
      if (mood !== 'neutral') moodEl.classList.add('mood-' + mood);
    }

    // 剧情线 pill（如果有当前剧情线名称）
    let storylineEl = document.getElementById('state-storyline');
    const storylineName = state.storyline_name || '';
    if (storylineName) {
      if (!storylineEl) {
        storylineEl = document.createElement('span');
        storylineEl.id = 'state-storyline';
        storylineEl.className = 'state-pill storyline-pill';
        // 插入到心情 pill 之后
        if (moodEl && moodEl.parentNode) {
          moodEl.parentNode.insertBefore(storylineEl, moodEl.nextSibling);
        }
      }
      storylineEl.textContent = '📖 ' + storylineName;
    } else if (storylineEl) {
      storylineEl.remove();
    }

    barEl.style.display = '';
  }

   async function loadCharacterState(characterId) {
     try {
       const result = await API.getCharacterState(characterId);
       if (result?.state) {
         // 把 show_bar 合并到 state 中，供 renderStateBar 判断显隐
         result.state.show_bar = result.show_bar;
         renderStateBar(result.state);
       }
     } catch (_) {
       // 未登录或接口出错时静默忽略，不影响正常聊天
     }
   }

  /* ── 角色状态面板由 chat-status-panel.js 提供（ChatStatusPanel） ── */

   async function enterChat(char) {
    currentChar = normalizeCharacter(char);
    history = [];
    _lastMsgTimestamp = 0;
    _shownEventIds.clear();
     AppState.setLastCharacterId(currentChar.id);
     updateChatHeader(currentChar);
     document.getElementById('chat-messages').innerHTML = '';
    initSmartScroll();
     appendDateDivider();
     // 重置角色状态面板（换角色时清空上一个角色的状态）
     ChatStatusPanel.reset();
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
       // 游客模式展示模拟状态栏（不持久化）
       renderStateBar({
         affection: 0,
         story_phase: 'stranger',
         mood: 'neutral',
         show_bar: true,
       });
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

  /** 通用头像渲染：将 rawImg 或 fallback 文字应用到目标元素。 */
  function _applyAvatar(el, rawImg, fallbackChar, fallbackBg = 'linear-gradient(135deg,#8a72ff,#ff7eb6)', altName = '') {
    const imgSrc = rawImg ? (rawImg.startsWith('/') ? SERVER_ORIGIN + rawImg : rawImg) : null;
    if (imgSrc) {
      const img = document.createElement('img');
      img.src = imgSrc;
      img.alt = altName;
      img.style.cssText = 'width:100%;height:100%;object-fit:cover;border-radius:inherit';
      img.onerror = () => { el.textContent = fallbackChar; el.style.background = fallbackBg; };
      el.innerHTML = '';
      el.style.background = 'none';
      el.appendChild(img);
    } else {
      el.textContent = fallbackChar;
      el.style.background = fallbackBg;
    }
    return el;
  }

  function updateChatHeader(char) {
    const avatarEl = document.getElementById('chat-avatar');
    const rawImg = char.avatarImg || char.coverImg || null;
    const fallbackChar = char.abbr || (char.display_name || char.name || '角')[0];
    const fallbackBg = char.color || 'linear-gradient(135deg,#8a72ff,#ff7eb6)';
    _applyAvatar(avatarEl, rawImg, fallbackChar, fallbackBg, char.display_name || char.name || '');

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

    if (type === 'char' && charData) {
      const rawImg = charData.avatarImg || charData.coverImg || null;
      const fallbackChar = charData.abbr || (charData.display_name || charData.name || '角')[0];
      const fallbackBg = charData.color || 'linear-gradient(135deg,#8a72ff,#ff7eb6)';
      _applyAvatar(el, rawImg, fallbackChar, fallbackBg, charData.display_name || charData.name || '');
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

   /* ── 文本渲染 & 状态栏处理 ───────────────────────────────────── */

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
    const { cleanText, statusRaw } = ChatStatusPanel.stripStatusBlock(text);
    if (statusRaw !== null) {
      ChatStatusPanel.render(statusRaw);
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

   /* ── 流式消息状态管理 ─────────────────────────────────────────── */

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

  // 已展示过的剧情事件ID集合，避免重复提示
  const _shownEventIds = new Set();

  function syncCharacterState(payload) {
    if (payload?.character_state) {
      renderStateBar(payload.character_state);
    }
    // 剧情事件通知：触发的事件以顶部滑入提示条展示
    const events = payload?.character_state?.triggered_events || payload?.triggered_events || [];
    if (events.length > 0) {
      for (const ev of events) {
        const evId = ev.id;
        if (evId && _shownEventIds.has(evId)) continue;
        if (evId) _shownEventIds.add(evId);
        showStoryEventToast(ev);
      }
    }
  }

  /** 剧情事件解锁提示条（顶部滑入，点击展开详情） */
  function showStoryEventToast(eventData) {
    const container = document.getElementById('chat-messages');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = 'story-event-toast';
    const title = eventData.title || '剧情解锁';
    const desc = eventData.description || '';
    toast.innerHTML = `
      <div class="event-title">🎬 ${escapeHtml(title)}</div>
      ${desc ? `<div class="event-desc">${escapeHtml(desc)}</div>` : ''}
    `;
    if (eventData.unlocked) {
      toast.style.cursor = 'pointer';
      toast.onclick = () => showEventDetail(eventData);
    }
    container.parentElement.insertBefore(toast, container);
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
      toast.classList.remove('show');
      setTimeout(() => toast.remove(), 400);
    }, 4000);
  }

  function showEventDetail(eventData) {
    const unlocked = eventData.unlocked || {};
    const parts = [];
    if (unlocked.memories?.length) parts.push(`解锁记忆 ${unlocked.memories.length} 条`);
    if (unlocked.greetings?.length) parts.push(`解锁开场白 ${unlocked.greetings.length} 个`);
    if (unlocked.storyline_id) parts.push('解锁新剧情线');
    const content = eventData.event_content || parts.join('、') || '剧情已解锁';
    UI.toast(`${eventData.title}\n\n${content}`, 'info', 5000);
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

  /* ── 消息操作按钮 ────────────────────────────────────────────── */

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

  /* ── 历史渲染 & 角色资料管理 ──────────────────────────────────── */

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

   /* ── 消息发送核心 ────────────────────────────────────────────── */

  /** 构建流式消息处理器。loggedIn=true 时追加角色状态同步和持久化操作。 */
  function buildStreamHandlers(streamState, userText, { loggedIn = false } = {}) {
    return {
      onChunk(chunk) {
        handleStreamChunk(streamState, chunk);
      },
      onDone(payload) {
        finalizeStreamReply(streamState, payload?.reply);
        const msgId = loggedIn ? (payload?.message_id || null) : null;
        appendLocalConversation(userText, streamState.aiText, msgId);
        if (loggedIn) {
          syncCharacterState(payload);
          bindPersistedStreamActions(streamState, msgId);
        } else {
          hideStreamActionButtons(streamState);
        }
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
          buildStreamHandlers(streamState, text),
          _streamController.signal
        );
        await refreshGuestQuota();
      } else {
        await API.streamMessage(
          {
            character_id: currentChar.id,
            message: text,
          },
          buildStreamHandlers(streamState, text, { loggedIn: true }),
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
     toggleStatusPanel: ChatStatusPanel.toggle,
     get currentChar() { return currentChar; },
     get history() { return history; },
   };
 })();

