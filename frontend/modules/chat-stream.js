/** chat-stream.js — SSE 流式状态机、消息收发流程 */
const ChatStream = ((ChatState) => {
  const R = ChatState.render;  // shorthand for render module

  /* ── 流式状态管理 ────────────────────────────────────── */
  function createStreamState() {
    return { bubbleEl: null, actionBtnsEl: null, streamRowEl: null, aiText: '' };
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
    ChatState.history.push({ role: 'user', content: userText, created_at: createdAt });
    ChatState.history.push(R.createAssistantHistoryEntry(assistantText, messageId, createdAt));
    if (ChatState.history.length > 300) {
      ChatState.history = ChatState.history.slice(-300);
    }
  }

  function hideStreamActionButtons(streamState) {
    if (streamState.actionBtnsEl) streamState.actionBtnsEl.style.display = 'none';
  }

  function bindPersistedStreamActions(streamState, messageId) {
    if (!messageId) { hideStreamActionButtons(streamState); return; }
    R.assignMessageId(streamState.streamRowEl, messageId);
    ChatState.bindMessageActionButtons(streamState.actionBtnsEl, streamState.streamRowEl, streamState.bubbleEl, messageId);
  }

  function cleanupStreamError(streamState) {
    cleanupStreamState(streamState);
  }

  function handleStreamError(streamState, payload, fallbackMessage = '网络波动，请稍后再试') {
    cleanupStreamError(streamState);
    UI.toast(payload?.message || fallbackMessage, 'warn', 3000);
  }

  /* ── 流式行管理 ──────────────────────────────────────── */
  function resetStreamState(state) {
    state.bubbleEl = null; state.actionBtnsEl = null; state.streamRowEl = null; state.aiText = '';
    return state;
  }

  function assignStreamState(state, streamRow, initialText = '') {
    state.bubbleEl = streamRow.bubble; state.actionBtnsEl = streamRow.actionBtns;
    state.streamRowEl = streamRow.row; state.aiText = initialText;
    return state;
  }

  function attachStreamRow(state, streamRow, initialText = '') {
    assignStreamState(state, streamRow, initialText);
    if (initialText) R.renderMessageBubble(state.bubbleEl, state.aiText, true);
    return state;
  }

  function ensureStreamState(state, initialText = '') {
    if (state.bubbleEl) return state;
    R.removeTyping();
    return attachStreamRow(state, createStreamRow(), initialText);
  }

  function ensureStreamReplyRow(state, initialText = '') { return ensureStreamState(state, initialText); }

  function renderStreamReply(state, nextText) {
    ensureStreamState(state);
    state.aiText = nextText;
    R.renderMessageBubble(state.bubbleEl, state.aiText, true);
    ChatState.scrollToBottom();
  }

  function discardStreamReply(state) { cleanupStreamState(state); }

  function cleanupStreamState(state) {
    R.removeTyping();
    R.removeRowIfPresent(state?.streamRowEl);
    return resetStreamState(state);
  }

  /* ── AI 消息行工厂 ──────────────────────────────────── */
  function createAiMessageElements(hiddenActions = false) {
    const row = R.createMessageRow('ai');
    R.appendRowAvatar(row, 'char', ChatState.currentChar);
    const bubble = R.createMessageBubble('ai');
    const actionBtns = R.createAssistantActionButtons(row, bubble, null, hiddenActions);
    R.appendAssistantBubble(row, bubble, actionBtns);
    return { row, bubble, actionBtns };
  }

  function insertMessageRow(container, row, nextSibling = null) {
    if (nextSibling) { container.insertBefore(row, nextSibling); return row; }
    container.appendChild(row); return row;
  }

  function placeAiMessageRow(container, row, nextSibling = null, shouldScroll = false) {
    insertMessageRow(container, row, nextSibling);
    if (shouldScroll) ChatState.scrollToBottom();
    return row;
  }

  function appendMessageTimeIfNeeded(container, timestamp, date = new Date()) {
    if (R.shouldShowTime(timestamp)) R.appendMessageTime(container, date);
    return container;
  }

  function configureAiMessageRow(row, bubble, messageId = null, getText = null) {
    R.assignMessageId(row, messageId);
    if (getText) R.bindCopyHandlers(bubble, getText);
    return row;
  }

  function initializeAiMessageRow(container, timestamp, opts = {}) {
    const { nextSibling = null, hiddenActions = false, shouldScroll = false, messageId = null, getText = null } = opts;
    appendMessageTimeIfNeeded(container, timestamp, new Date());
    const aiMessageRow = createAiMessageElements(hiddenActions);
    configureAiMessageRow(aiMessageRow.row, aiMessageRow.bubble, messageId, getText);
    placeAiMessageRow(container, aiMessageRow.row, nextSibling, shouldScroll);
    return aiMessageRow;
  }

  function createStreamRow() {
    const box = document.getElementById('chat-messages');
    const msgTime = Date.now();
    const streamRow = initializeAiMessageRow(box, msgTime, { hiddenActions: true, shouldScroll: true });
    ChatState.lastMsgTimestamp = msgTime;
    return streamRow;
  }

  function createContinuationMessageRow(sourceRowEl, messageId, getText) {
    const box = document.getElementById('chat-messages');
    const contMsgTime = Date.now();
    const { row, bubble, actionBtns } = initializeAiMessageRow(box, contMsgTime, { nextSibling: sourceRowEl.nextSibling, messageId, getText });
    ChatState.lastMsgTimestamp = contMsgTime;
    return { row, bubble, actionBtns };
  }

  /* ── 历史消息更新 ────────────────────────────────────── */
  function updateAssistantHistoryMessage(messageId, content, nextMessageId = messageId) {
    let msgIdx = -1;
    for (let i = ChatState.history.length - 1; i >= 0; i--) {
      if (ChatState.history[i].message_id === messageId || (ChatState.history[i].role === 'assistant' && !ChatState.history[i].message_id)) {
        msgIdx = i; break;
      }
    }
    if (msgIdx !== -1) {
      ChatState.history[msgIdx] = { ...ChatState.history[msgIdx], content, created_at: new Date().toISOString(), message_id: nextMessageId || messageId };
    }
  }

  function finalizeAssistantMessageUpdate(messageId, content, payload, fallbackMessageId = messageId) {
    updateAssistantHistoryMessage(messageId, content, payload?.message_id || fallbackMessageId);
    syncCharacterState(payload);
  }

  /* ── 角色状态 & 事件 ─────────────────────────────────── */
  const AFFECTION_MILESTONES = [20, 40, 60, 80, 100];

  function syncCharacterState(payload) {
    let deltaInfo = null;
    if (payload?.character_state && ChatState.renderStateBar) {
      deltaInfo = ChatState.renderStateBar(payload.character_state);
    }
    // 好感度里程碑检测
    if (deltaInfo && deltaInfo.prevAffection < deltaInfo.newAffection) {
      for (const m of AFFECTION_MILESTONES) {
        if (deltaInfo.prevAffection < m && deltaInfo.newAffection >= m) {
          const label = (ChatState.currentChar?.card_type === 'scenario') ? '沉浸度' : '好感度';
          UI.toast(label + '达到 ' + m + '！', 'info', 2500);
        }
      }
    }
    const events = payload?.character_state?.triggered_events || payload?.triggered_events || [];
    if (events.length > 0) {
      for (const ev of events) {
        const evId = ev.id;
        if (evId && ChatState.shownEventIds.has(evId)) continue;
        if (evId) ChatState.shownEventIds.add(evId);
        showStoryEventToast(ev);
      }
    }
  }

  function showStoryEventToast(eventData) {
    const container = document.getElementById('chat-messages');
    if (!container) return;
    const toast = document.createElement('div');
    const isUpgrade = eventData.type === 'phase_upgrade';
    toast.className = isUpgrade ? 'story-event-toast phase-upgrade-toast' : 'story-event-toast';
    const title = eventData.title || '剧情解锁';
    const desc = eventData.description || '';
    const icon = isUpgrade ? '💕' : '🎬';
    toast.innerHTML = `<div class="event-title">${icon} ${escapeHtml(title)}</div>${desc ? `<div class="event-desc">${escapeHtml(desc)}</div>` : ''}`;
    if (eventData.unlocked) {
      toast.style.cursor = 'pointer';
      toast.onclick = () => showEventDetail(eventData);
    }
    container.parentElement.insertBefore(toast, container);
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 400); }, 4000);
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

  /* ── 按钮状态 ────────────────────────────────────────── */
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
    ChatState.setSending(true);
    if (showTypingBubble) R.showTyping();
    ChatState.abortStream();
    ChatState.streamController = new AbortController();
    if (loading === 'regenerate') {
      setButtonLoading(buttons.regenerate, true, true);
      setButtonLoading(buttons.continue, true);
    } else if (loading === 'continue') {
      setButtonLoading(buttons.regenerate, true);
      setButtonLoading(buttons.continue, true, true);
    }
    if (hideActions) setActionButtonsVisible(buttons.actions, false);
    return buttons;
  }

  function completeMessageAction(buttons = {}, { loading = null, restoreActions = false } = {}) {
    if (loading === 'regenerate') { setButtonLoading(buttons.regenerate, false, false); setButtonLoading(buttons.continue, false); }
    else if (loading === 'continue') { setButtonLoading(buttons.regenerate, false); setButtonLoading(buttons.continue, false, false); }
    if (restoreActions) setActionButtonsVisible(buttons.actions, true);
    R.removeTyping();
    ChatState.setSending(false);
    return buttons;
  }

  function resolveContinuationResult(originalText, appendedText, payload, messageId) {
    const finalAppended = payload?.appended_text || appendedText;
    const nextMessageId = payload?.message_id || messageId;
    return { finalAppended, nextMessageId, fullText: `${originalText || ''}${finalAppended}` };
  }

  function cleanupContinuationFailure(newRowEl, originalButtons, message) {
    R.removeTyping();
    R.removeRowIfPresent(newRowEl);
    UI.toast(message, 'warn', 3000);
    setActionButtonsVisible(originalButtons?.actions, true);
  }

  /* ── 消息流构建 ──────────────────────────────────────── */
  function buildStreamHandlers(streamState, userText, { loggedIn = false } = {}) {
    return {
      onChunk(chunk) { handleStreamChunk(streamState, chunk); },
      onDone(payload) {
        finalizeStreamReply(streamState, payload?.reply);
        const msgId = loggedIn ? (payload?.message_id || null) : null;
        appendLocalConversation(userText, streamState.aiText, msgId);
        if (loggedIn) {
          syncCharacterState(payload);
          bindPersistedStreamActions(streamState, msgId);
        } else {
          if (payload?.character_state) syncCharacterState(payload);
          hideStreamActionButtons(streamState);
        }
      },
      onError() { cleanupStreamError(streamState); },
    };
  }

  return {
    createStreamState, handleStreamChunk, finalizeStreamReply,
    appendLocalConversation, hideStreamActionButtons, bindPersistedStreamActions, cleanupStreamError, handleStreamError,
    resetStreamState, assignStreamState, attachStreamRow,
    ensureStreamState, ensureStreamReplyRow, renderStreamReply,
    discardStreamReply, cleanupStreamState,
    createAiMessageElements, insertMessageRow, placeAiMessageRow,
    appendMessageTimeIfNeeded, configureAiMessageRow, initializeAiMessageRow,
    createStreamRow, createContinuationMessageRow,
    updateAssistantHistoryMessage, finalizeAssistantMessageUpdate,
    syncCharacterState, showStoryEventToast, showEventDetail,
    setButtonLoading, setActionButtonsVisible, getMessageActionButtons,
    beginMessageAction, completeMessageAction,
    resolveContinuationResult, cleanupContinuationFailure,
    buildStreamHandlers,
  };
});
