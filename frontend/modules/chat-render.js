/** chat-render.js — 消息渲染、气泡、头像、时间线 */
const ChatRender = ((ChatState) => {
  /* ── 文本渲染 ─────────────────────────────────────────── */
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
    if (statusRaw !== null) ChatStatusPanel.render(statusRaw);
    return cleanText;
  }

  function renderTextWithLineBreaks(el, text, isAssistant = false) {
    el.innerHTML = '';
    const displayText = resolveDisplayText(text, isAssistant);
    const cleaned = normalizeRenderedText(displayText);
    const lines = cleaned.split('\n');
    appendTextLines(el, lines);
  }

  /* ── 时间显示 ────────────────────────────────────────── */
  function shouldShowTime(timestamp) {
    if (!ChatState.lastMsgTimestamp) return true;
    const gap = Math.abs(timestamp - ChatState.lastMsgTimestamp);
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

  function appendMessageTime(container, date) {
    const timeEl = document.createElement('div');
    timeEl.className = 'msg-time';
    timeEl.textContent = formatSmartTime(date);
    container.appendChild(timeEl);
    return timeEl;
  }

  function appendDividerNode(text, container) {
    const node = document.createElement('div');
    node.className = 'date-divider';
    node.textContent = text;
    container.appendChild(node);
    return node;
  }

  function appendDateDivider(container) {
    return appendDividerNode(formatDate(new Date()), container);
  }

  function appendLoadingHint(text, container) {
    return appendDividerNode(text, container);
  }

  /* ── 头像渲染 ────────────────────────────────────────── */
  function applyAvatar(el, rawImg, fallbackChar, fallbackBg, altName) {
    const imgSrc = rawImg ? (rawImg.startsWith('/') ? (typeof SERVER_ORIGIN !== 'undefined' ? SERVER_ORIGIN : '') + rawImg : rawImg) : null;
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

  function createMsgAvatar(type, charData = null) {
    const el = document.createElement('div');
    el.className = 'msg-avatar';
    if (type === 'char' && charData) {
      const rawImg = charData.avatarImg || charData.coverImg || null;
      const fallbackChar = charData.abbr || (charData.display_name || charData.name || '角')[0];
      const fallbackBg = charData.color || 'linear-gradient(135deg,#8a72ff,#ff7eb6)';
      applyAvatar(el, rawImg, fallbackChar, fallbackBg, charData.display_name || charData.name || '');
      return el;
    }
    if (type === 'user') {
      const user = Auth.getUser && Auth.getUser();
      const avatarUrl = user?.avatar_url;
      if (avatarUrl) {
        const img = document.createElement('img');
        img.src = avatarUrl.startsWith('/') ? (typeof SERVER_ORIGIN !== 'undefined' ? SERVER_ORIGIN : '') + avatarUrl : avatarUrl;
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

  function appendRowAvatar(row, type, charData = null) {
    const avatarEl = createMsgAvatar(type, charData);
    if (avatarEl) row.appendChild(avatarEl);
    return avatarEl;
  }

  /* ── 顶部栏 ──────────────────────────────────────────── */
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
    const rawImg = char.avatarImg || char.coverImg || null;
    const fallbackChar = char.abbr || (char.display_name || char.name || '角')[0];
    const fallbackBg = char.color || 'linear-gradient(135deg,#8a72ff,#ff7eb6)';
    applyAvatar(avatarEl, rawImg, fallbackChar, fallbackBg, char.display_name || char.name || '');
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

  /* ── 消息气泡 ────────────────────────────────────────── */
  function fillErrorBubble(bubble, text, row, retryText = null) {
    bubble.innerHTML = `⚠ ${escapeHtml(text)}`;
    if (!retryText) return bubble;
    const btn = createRetryButton(row, retryText);
    bubble.appendChild(document.createElement('br'));
    bubble.appendChild(btn);
    return bubble;
  }

  function createRetryButton(row, retryText) {
    const btn = document.createElement('div');
    btn.className = 'retry-btn';
    btn.textContent = '🔄 重新发送';
    btn.addEventListener('click', () => { retryMessage(row, retryText); });
    return btn;
  }

  function retryMessage(row, retryText) {
    row.remove();
    const input = document.getElementById('chat-input');
    input.value = retryText;
    if (ChatState.sendMessage) ChatState.sendMessage();
    return input;
  }

  function assignMessageId(target, messageId = null) {
    if (target && messageId) target.dataset.messageId = messageId;
    return target;
  }

  function createAssistantHistoryEntry(content, messageId = null, createdAt) {
    return { role: 'assistant', content, created_at: createdAt || new Date().toISOString(), ...(messageId ? { message_id: messageId } : {}) };
  }

  function createMessageRow(roleClass, messageId = null) {
    const row = document.createElement('div');
    row.className = `msg-row ${roleClass}`;
    assignMessageId(row, messageId);
    return row;
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

  function createMessageActionButtons(hidden = false) {
    const actionBtns = document.createElement('div');
    actionBtns.className = 'msg-action-btns';
    actionBtns.innerHTML = `<button class="msg-action-btn regenerate-btn" title="重新生成">↻</button><button class="msg-action-btn continue-btn" title="继续生成">▶</button>`;
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

  function appendAssistantBubble(row, bubble, actionBtns = null) {
    appendMessageBody(row, bubble, actionBtns);
    return bubble;
  }

  function createAssistantActionButtons(row = null, bubble = null, messageId = null, hiddenActions = false) {
    const actionBtns = createMessageActionButtons(hiddenActions);
    if (messageId) ChatState.bindMessageActionButtons(actionBtns, row, bubble, messageId);
    return actionBtns;
  }

  function mountAssistantBubble(row, bubble, messageId = null) {
    const actionBtns = messageId ? createAssistantActionButtons(row, bubble, messageId) : null;
    appendAssistantBubble(row, bubble, actionBtns);
    return actionBtns;
  }

  function appendBubbleContent(row, bubble, isAi, messageId) {
    if (isAi) { mountAssistantBubble(row, bubble, messageId); return; }
    appendPlainBubble(row, bubble);
  }

  function appendMsg(role, text, createdAt = null, retryText = null, messageId = null) {
    const normalizedRole = role === 'ai' ? 'assistant' : role;
    const isError = normalizedRole === 'error';
    const container = ChatState.batchContainer || document.getElementById('chat-messages');
    const msgTime = createdAt ? new Date(createdAt).getTime() : Date.now();
    if (shouldShowTime(msgTime)) appendMessageTime(container, createdAt ? new Date(createdAt) : new Date());
    const row = createMessageRow((normalizedRole === 'assistant' || isError) ? 'ai' : normalizedRole, messageId);
    const isAi = normalizedRole === 'assistant';
    if (isAi && !isError) appendRowAvatar(row, 'char', ChatState.currentChar);
    const bubble = createMessageBubble(isError ? 'error-bubble' : (normalizedRole === 'assistant' ? 'ai' : normalizedRole));
    if (isError) {
      fillErrorBubble(bubble, text, row, retryText);
      appendPlainBubble(row, bubble);
    } else {
      renderMessageBubble(bubble, text, normalizedRole === 'assistant');
      bindCopyHandlers(bubble, () => text);
      appendBubbleContent(row, bubble, isAi, messageId);
    }
    if (!isAi) appendRowAvatar(row, 'user');
    container.appendChild(row);
    ChatState.lastMsgTimestamp = msgTime;
    if (!ChatState.batchContainer) { ChatState.scrollToBottom(); if (ChatState.pruneDOM) ChatState.pruneDOM(); }
    return row;
  }

  function removeLatestUserMessage(text) {
    const box = document.getElementById('chat-messages');
    if (!box) return false;
    const rows = Array.from(box.querySelectorAll('.msg-row.user'));
    const target = rows[rows.length - 1];
    if (!target) return false;
    const bubble = target.querySelector('.msg-bubble.user');
    if (text != null && bubble && bubble.textContent !== text) return false;
    target.remove();
    return true;
  }

  /* ── 打字中 & 复制 ──────────────────────────────────── */
  function fillTypingBubble(bubble) {
    bubble.innerHTML = `<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>`;
    return bubble;
  }

  function showTyping() {
    const box = document.getElementById('chat-messages');
    const row = createMessageRow('ai');
    row.id = 'typing-row';
    appendRowAvatar(row, 'char', ChatState.currentChar);
    const bubble = fillTypingBubble(createMessageBubble('typing'));
    row.appendChild(bubble);
    box.appendChild(row);
    ChatState.scrollToBottom();
  }

  function removeTyping() { removeElementById('typing-row'); }

  function flashElementClass(el, className, delay = 1800) {
    if (!el) return null;
    el.classList.add(className);
    setTimeout(() => el.classList.remove(className), delay);
    return el;
  }

  function showCopyToast() { flashElementClass(document.getElementById('copy-toast'), 'show'); }

  function copyMessageText(getText) {
    return navigator.clipboard.writeText(getText()).then(() => { showCopyToast(); });
  }

  function bindCopyHandlers(bubbleEl, getText) {
    const doCopy = () => copyMessageText(getText);
    bubbleEl.addEventListener('dblclick', doCopy);
    let pressTimer;
    bubbleEl.addEventListener('touchstart', () => { pressTimer = setTimeout(doCopy, 600); }, { passive: true });
    bubbleEl.addEventListener('touchend', () => clearTimeout(pressTimer), { passive: true });
    bubbleEl.addEventListener('touchmove', () => clearTimeout(pressTimer), { passive: true });
  }

  /* ── DOM 辅助 ────────────────────────────────────────── */
  function removeRowIfPresent(rowEl) { if (rowEl?.parentNode) rowEl.remove(); }
  function removeElementById(elementId) { const el = document.getElementById(elementId); removeRowIfPresent(el); return el; }

  return {
    normalizeRenderedText, appendTextLines, resolveDisplayText, renderTextWithLineBreaks,
    shouldShowTime, formatSmartTime, appendMessageTime, appendDividerNode, appendDateDivider, appendLoadingHint,
    applyAvatar, createMsgAvatar, appendRowAvatar,
    appendHeaderSign, updateChatHeader,
    fillErrorBubble, createRetryButton, retryMessage,
    assignMessageId, createAssistantHistoryEntry,
    createMessageRow, createMessageBubble, renderMessageBubble,
    appendPlainBubble, appendAssistantBubble, createMessageActionButtons,
    createAssistantActionButtons, mountAssistantBubble, appendBubbleContent, appendMessageBody,
    appendMsg, removeLatestUserMessage, fillTypingBubble, showTyping, removeTyping,
    flashElementClass, showCopyToast, copyMessageText, bindCopyHandlers,
    removeRowIfPresent, removeElementById,
  };
});
