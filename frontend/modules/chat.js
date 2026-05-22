/** chat.js — 聊天模块协调入口，拥有共享状态，连接 render/stream/actions 子模块 */
const Chat = (() => {
  /* ── 共享状态 ────────────────────────────────────────── */
  const ChatState = {
    currentChar: null,
    isSending: false,
    history: [],
    streamController: null,
    batchContainer: null,
    autoScroll: true,
    historyPage: 1,
    historyHasMore: false,
    historyLoadingMore: false,
    guestQuota: null,
    lastMsgTimestamp: 0,
    lastState: null,
    shownEventIds: new Set(),

    // 跨模块回调（子模块注册）
    scrollToBottom: null,
    setSending: null,
    abortStream: null,
    sendMessage: null,
    renderStateBar: null,
    bindMessageActionButtons: null,
  };

  /* ── 接入子模块 ──────────────────────────────────────── */
  ChatState.render = ChatRender(ChatState);
  ChatState.stream = ChatStream(ChatState);
  const Actions = ChatActions(ChatState);
  ChatState.bindMessageActionButtons = Actions.bindMessageActionButtons;

  const R = ChatState.render;
  const S = ChatState.stream;

  /* ── DOM 节点上限 ────────────────────────────────────── */
  const MAX_DOM_MESSAGES = 200;
  const DOM_PRUNE_COUNT = 50;

  function _pruneOldMessageDOM() {
    const box = document.getElementById('chat-messages');
    if (!box) return;
    const rows = box.querySelectorAll('.msg-row');
    if (rows.length <= MAX_DOM_MESSAGES) return;
    // 仅在用户位于底部时淘汰（避免干扰正在翻阅历史的用户）
    if (!ChatState.autoScroll) return;
    // 测量即将移除的行高度
    let removedHeight = 0;
    const toRemove = [];
    for (let i = 0; i < DOM_PRUNE_COUNT && i < rows.length; i++) {
      removedHeight += rows[i].offsetHeight;
      toRemove.push(rows[i]);
    }
    const scrollTopBefore = box.scrollTop;
    toRemove.forEach(r => r.remove());
    // 用等高管占位 div 维持滚动位置稳定
    const spacer = document.createElement('div');
    spacer.className = 'folded-messages-spacer';
    spacer.style.height = removedHeight + 'px';
    spacer.innerHTML = '<span class="folded-hint">📦 较早的消息已折叠以节省内存</span>';
    box.insertBefore(spacer, box.firstChild);
    box.scrollTop = scrollTopBefore;
    // 更新折叠计数
    const existing = parseInt(spacer.dataset.foldedCount || '0', 10);
    spacer.dataset.foldedCount = existing + DOM_PRUNE_COUNT;
  }
  ChatState.pruneDOM = _pruneOldMessageDOM;

  /* ── 辅助函数 ────────────────────────────────────────── */
  function abortStream() {
    if (ChatState.streamController) { ChatState.streamController.abort(); ChatState.streamController = null; }
  }
  ChatState.abortStream = abortStream;

  function setSending(bool) {
    ChatState.isSending = bool;
    const btn = document.getElementById('send-btn');
    btn.disabled = bool;
    btn.classList.toggle('loading', bool);
  }
  ChatState.setSending = setSending;

  function scrollToBottom(force = false) {
    if (!force && !ChatState.autoScroll) return;
    const box = document.getElementById('chat-messages');
    box.scrollTop = box.scrollHeight;
  }
  ChatState.scrollToBottom = scrollToBottom;

  function initSmartScroll() {
    const box = document.getElementById('chat-messages');
    if (!box) return;
    // 幂等绑定：先移除旧监听器防止重复累积
    if (ChatState._scrollHandler) {
      box.removeEventListener('scroll', ChatState._scrollHandler);
    }
    const THRESHOLD = 120;
    ChatState._scrollHandler = () => {
      const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < THRESHOLD;
      ChatState.autoScroll = atBottom;
    };
    box.addEventListener('scroll', ChatState._scrollHandler, { passive: true });
  }

  /* ── 关系状态栏 ──────────────────────────────────────── */
  const INTIMATE_PHASE_LABELS = { stranger: '陌生人', acquaintance: '熟人', friend: '朋友', lover: '恋人' };
  const SCENARIO_PHASE_LABELS = { stranger: '初入', acquaintance: '探索', friend: '深入', lover: '终章' };
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
    const ct = (ChatState.currentChar && ChatState.currentChar.card_type) || 'intimate';
    return ct === 'scenario'
      ? { phase: SCENARIO_PHASE_LABELS, mood: SCENARIO_MOOD_LABELS, affectionName: '沉浸度' }
      : { phase: INTIMATE_PHASE_LABELS, mood: INTIMATE_MOOD_LABELS, affectionName: '好感度' };
  }

  function _isStateBarHidden() {
    if (ChatState.lastState && ChatState.lastState.show_bar === false) return true;
    if (ChatState.currentChar) {
      try { const rules = JSON.parse(ChatState.currentChar.affection_rules_json || '{}'); return rules.show_bar === false; } catch (_) {}
    }
    return false;
  }

  function renderStateBar(state) {
    const barEl = document.getElementById('chat-state-bar');
    if (!barEl || !state) return;
    // 计算好感度变化量（在覆盖 lastState 之前）
    const prevAffection = ChatState.lastState ? (ChatState.lastState.affection || 0) : (state.affection || 0);
    const newAffection = Math.max(0, Math.min(100, state.affection || 0));
    const affectionDelta = newAffection - prevAffection;
    ChatState.lastState = state;
    if (_isStateBarHidden()) { barEl.style.display = 'none'; return { prevAffection, newAffection }; }
    const phase = state.story_phase || 'stranger';
    const mood = state.mood || 'neutral';
    const labels = _getLabels();
    const labelEl = document.getElementById('state-affection-label');
    if (labelEl) labelEl.textContent = labels.affectionName;
    const fill = document.getElementById('affection-bar-fill');
    if (fill) { fill.style.width = newAffection + '%'; fill.classList.toggle('full', newAffection >= 100); }
    const valEl = document.getElementById('affection-value');
    if (valEl) {
      valEl.textContent = newAffection;
      // 好感度变化动画提示
      if (affectionDelta !== 0) {
        valEl.classList.remove('affection-pop');
        void valEl.offsetWidth; // 强制回流以重新触发动画
        valEl.classList.add('affection-pop');
        valEl.setAttribute('data-delta', (affectionDelta > 0 ? '+' : '') + affectionDelta);
      }
    }
    const phaseEl = document.getElementById('state-phase');
    if (phaseEl) phaseEl.textContent = labels.phase[phase] || phase;
    const moodEl = document.getElementById('state-mood');
    if (moodEl) {
      moodEl.textContent = labels.mood[mood] || mood;
      MOOD_CLASSES.forEach(m => moodEl.classList.remove('mood-' + m));
      if (mood !== 'neutral') moodEl.classList.add('mood-' + mood);
    }
    let storylineEl = document.getElementById('state-storyline');
    const storylineName = state.storyline_name || '';
    if (storylineName) {
      if (!storylineEl) {
        storylineEl = document.createElement('span');
        storylineEl.id = 'state-storyline';
        storylineEl.className = 'state-pill storyline-pill';
        if (moodEl && moodEl.parentNode) moodEl.parentNode.insertBefore(storylineEl, moodEl.nextSibling);
      }
      storylineEl.textContent = '📖 ' + storylineName;
    } else if (storylineEl) { storylineEl.remove(); }
    barEl.style.display = '';
    return { prevAffection, newAffection };
  }
  ChatState.renderStateBar = renderStateBar;

  async function loadCharacterState(characterId) {
    try {
      const result = await API.getCharacterState(characterId);
      if (result?.state) { result.state.show_bar = result.show_bar; renderStateBar(result.state); }
    } catch (_) {}
  }

  /* ── 游客额度 ────────────────────────────────────────── */
  function renderGuestQuotaBar(quota) {
    let _quota = quota;
    if (Auth.isLoggedIn()) { const bar = document.getElementById('guest-trial-bar'); if (bar) bar.style.display = 'none'; return; }
    ChatState.guestQuota = _quota || ChatState.guestQuota;
    let bar = document.getElementById('guest-trial-bar');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'guest-trial-bar';
      bar.className = 'guest-trial-bar';
      const chatPage = document.getElementById('page-chat');
      const topbar = chatPage?.querySelector('.chat-topbar');
      if (topbar) topbar.after(bar); else if (chatPage) chatPage.prepend(bar);
    }
    const statusText = ChatState.guestQuota?.status_text || '额度充足';
    const remainingPercent = Number.isFinite(ChatState.guestQuota?.remaining_percent)
      ? Math.max(0, Math.min(100, ChatState.guestQuota.remaining_percent)) : 100;
    const statusClass = statusText.includes('已用完') ? 'exhausted' : (statusText.includes('不多') ? 'warning' : 'ok');
    bar.style.display = '';
    bar.innerHTML = `<div class="trial-copy"><span class="trial-label">游客体验额度</span><span class="trial-status ${statusClass}">${escapeHtml(statusText)}</span></div><div class="trial-meter"><span style="width:${remainingPercent}%"></span></div><button class="trial-login-btn" onclick="Auth.openLogin()">登录保存记录</button>`;
  }

  async function refreshGuestQuota() {
    if (Auth.isLoggedIn()) { renderGuestQuotaBar(null); return null; }
    try { const quota = await API.getGuestQuota(); renderGuestQuotaBar(quota); return quota; }
    catch (_) { renderGuestQuotaBar(ChatState.guestQuota || { status_text: '额度充足', remaining_percent: 100 }); return ChatState.guestQuota; }
  }

  /* ── 进入聊天 ────────────────────────────────────────── */
  function normalizeCharacter(char = {}) {
    return normalizeCharacterCardPayload({
      ...char,
      display_name: char.display_name || char.remark || char.name || '角色',
      sign: char.sign || char.custom_signature || char.subtitle || '',
      remark: char.remark || '',
      custom_signature: char.custom_signature || '',
    });
  }

  function getDisplayMeta() {
    if (!ChatState.currentChar) return { displayName: 'TA', rawName: '', sign: '' };
    return {
      displayName: ChatState.currentChar.display_name || ChatState.currentChar.remark || ChatState.currentChar.name || 'TA',
      rawName: ChatState.currentChar.name || '',
      sign: ChatState.currentChar.sign || ChatState.currentChar.custom_signature || ChatState.currentChar.subtitle || '',
    };
  }

  function syncCharacterInList(updatedChar) {
    if (!updatedChar?.id) return;
    CHARACTERS = CHARACTERS.map(item => item.id === updatedChar.id ? { ...item, ...updatedChar } : item);
  }

  async function refreshCurrentCharacterProfile() {
    if (!ChatState.currentChar) return null;
    const result = await safeApiCall(() => API.getCharacterProfile(ChatState.currentChar.id));
    ChatState.currentChar = normalizeCharacter(result.character || ChatState.currentChar);
    R.updateChatHeader(ChatState.currentChar);
    syncCharacterInList(ChatState.currentChar);
    return ChatState.currentChar;
  }

  function applyCharacterProfile(payload = {}) {
    if (!ChatState.currentChar) return;
    ChatState.currentChar = normalizeCharacter({ ...ChatState.currentChar, ...payload });
    R.updateChatHeader(ChatState.currentChar);
    syncCharacterInList(ChatState.currentChar);
  }

  async function clearCurrentChat() {
    if (!ChatState.currentChar) return;
    await safeApiCall(() => API.clearChatWithGreeting({ character_id: ChatState.currentChar.id, greeting_index: -1 }));
    await enterChat(ChatState.currentChar);
  }

  /* ── 历史消息加载 ────────────────────────────────────── */
  function renderHistory(messages) {
    const box = document.getElementById('chat-messages');
    box.innerHTML = '';
    ChatState.lastMsgTimestamp = 0;
    R.appendDateDivider(box);
    if (!messages.length) {
      // 新聊天室：显示友好引导
      const hint = document.createElement('div');
      hint.className = 'empty-chat-hint';
      hint.textContent = '发送第一条消息，开始你们的对话吧 ✨';
      box.appendChild(hint);
      return;
    }
    ChatState.batchContainer = document.createDocumentFragment();
    while (box.firstChild) { ChatState.batchContainer.appendChild(box.firstChild); }
    messages.forEach(item => R.appendMsg(item.role, item.content, item.created_at));
    box.appendChild(ChatState.batchContainer);
    ChatState.batchContainer = null;
    scrollToBottom();
    _pruneOldMessageDOM();
    if (ChatState.historyHasMore) renderLoadEarlierButton();
  }

  function renderLoadEarlierButton() {
    const box = document.getElementById('chat-messages');
    const existing = box.querySelector('.load-earlier-btn');
    if (existing) existing.remove();
    if (!ChatState.historyHasMore) return;
    const btn = document.createElement('div');
    btn.className = 'load-earlier-btn';
    btn.textContent = '⬆ 加载更早的消息';
    btn.onclick = loadEarlierMessages;
    box.insertBefore(btn, box.firstChild);
  }

  async function loadEarlierMessages() {
    if (ChatState.historyLoadingMore) return;
    ChatState.historyLoadingMore = true;
    const btn = document.querySelector('.load-earlier-btn');
    if (btn) { btn.textContent = '加载中…'; btn.onclick = null; }
    try {
      const pageToLoad = ChatState.historyPage + 1;
      const result = await API.getHistory(ChatState.currentChar.id, pageToLoad);
      ChatState.historyPage = pageToLoad;
      const olderMessages = result.messages || [];
      ChatState.historyHasMore = result.has_more || false;
      if (olderMessages.length > 0) {
        const box = document.getElementById('chat-messages');
        const firstChildBefore = box.children[btn ? 1 : 0];
        const scrollOffset = firstChildBefore ? firstChildBefore.getBoundingClientRect().top : 0;
        ChatState.history = [...olderMessages, ...ChatState.history];
        // 内存中最多保留 300 条，加载更早消息时优先保留最早的消息
        if (ChatState.history.length > 300) {
          ChatState.history = ChatState.history.slice(0, 300);
        }
        const frag = document.createDocumentFragment();
        olderMessages.forEach(item => { ChatState.batchContainer = frag; R.appendMsg(item.role, item.content, item.created_at); });
        ChatState.batchContainer = null;
        const insertBefore = btn || box.firstChild;
        while (frag.firstChild) { box.insertBefore(frag.firstChild, insertBefore); }
        if (firstChildBefore) { const newTop = firstChildBefore.getBoundingClientRect().top; box.scrollTop += newTop - scrollOffset; }
        _pruneOldMessageDOM();
      }
      if (ChatState.historyHasMore) renderLoadEarlierButton();
      else if (btn) btn.remove();
    } catch (err) {
      ChatState.batchContainer = null;
      if (btn) { btn.textContent = '加载失败：' + escapeHtml(err.message); btn.onclick = loadEarlierMessages; }
    } finally { ChatState.historyLoadingMore = false; }
  }

  async function enterChat(char) {
    ChatState.currentChar = normalizeCharacter(char);
    ChatState.history = [];
    ChatState.lastMsgTimestamp = 0;
    ChatState.shownEventIds.clear();
    AppState.setLastCharacterId(ChatState.currentChar.id);
    R.updateChatHeader(ChatState.currentChar);
    document.getElementById('chat-messages').innerHTML = '';
    initSmartScroll();
    R.appendDateDivider(document.getElementById('chat-messages'));
    ChatStatusPanel.reset();
    App.nav('chat');

    // 游客登录后恢复内存中的聊天历史
    var guestHistory = window.__guestChatHistory;
    var guestCharId = window.__guestChatCharId;
    if (guestHistory && guestHistory.length && guestCharId === ChatState.currentChar.id) {
      window.__guestChatHistory = null;
      window.__guestChatCharId = null;
    } else {
      guestHistory = null;
    }

    if (!Auth.isLoggedIn()) {
      const openingText = ChatState.currentChar.opening_message || ChatState.currentChar.first_message || '';
      if (openingText) { R.appendMsg('assistant', openingText); ChatState.history.push({ role: 'assistant', content: openingText }); }
      else R.appendMsg('assistant', `你好，我是${ChatState.currentChar.display_name || ChatState.currentChar.name}。`);
      renderStateBar({ affection: 0, story_phase: 'stranger', mood: 'neutral', show_bar: true });
      refreshGuestQuota();
      return;
    }
    R.appendLoadingHint('正在读取历史记录…', document.getElementById('chat-messages'));
    try {
      ChatState.historyPage = 1;
      const result = await API.getHistory(ChatState.currentChar.id, ChatState.historyPage);
      const mergedChar = normalizeCharacter(result.character || ChatState.currentChar);
      ChatState.currentChar = { ...ChatState.currentChar, ...mergedChar };
      ChatState.history = result.messages || [];
      ChatState.historyHasMore = result.has_more || false;
      // 合并游客历史到从数据库加载的历史前面
      if (guestHistory && guestHistory.length) {
        ChatState.history = [...guestHistory, ...ChatState.history];
        // 后台异步持久化游客历史
        _persistGuestHistory(ChatState.currentChar.id, guestHistory);
      }
      R.updateChatHeader(ChatState.currentChar);
      renderHistory(ChatState.history);
      if (ChatState.historyHasMore) renderLoadEarlierButton();
      loadCharacterState(ChatState.currentChar.id);
    } catch (err) {
      document.getElementById('chat-messages').innerHTML = '';
      R.appendDateDivider(document.getElementById('chat-messages'));
      R.appendMsg('assistant', `⚠ 历史读取失败：${escapeHtml(err.message)}`);
    }
  }

  /* ── 消息发送 ────────────────────────────────────────── */
  ChatState.sendMessage = send;

  async function handleSendFailure(err, userText) {
    if (!Auth.isLoggedIn()) {
      await refreshGuestQuota();
        // 额度不足时温和提醒登录
        if (ChatState.guestQuota && ChatState.guestQuota.remaining_percent > 0 && ChatState.guestQuota.remaining_percent <= 20) {
          if (!ChatState._guestQuotaWarnedLow) {
            ChatState._guestQuotaWarnedLow = true;
            UI.toast('今天的免费额度不多了，登录后可以无限畅聊', 'info', 3500);
          }
        }

      if ((err.message || '').includes('额度已用完')) {
        UI.toast('今日游客体验额度已用完，登录后可继续聊天', 'warn', 3200);
        setTimeout(() => Auth.openLogin(), 800);
      } else if ((err.message || '').includes('发送太快')) {
        UI.toast('发送太快了，请稍后再试', 'warn', 2500);
      }
    }
    R.removeTyping();
    R.appendMsg('error', `发送失败：${err.message}`, null, userText);
  }

  async function send() {
    if (ChatState.isSending) return;
    if (!ChatState.currentChar) return;
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text) return;
    R.appendMsg('user', text);
    input.value = '';
    input.style.height = 'auto';
    setSending(true);
    R.showTyping();
    abortStream();
    ChatState.streamController = new AbortController();
    if (window.innerWidth > 500) input.focus();
    const streamState = S.createStreamState();
    try {
      if (!Auth.isLoggedIn()) {
        const guestHistory = ChatState.history.slice(-8).map(m => ({ role: m.role, content: m.content }));
        await API.guestStreamMessage(
          { character_id: ChatState.currentChar.id, message: text, guest_history: guestHistory },
          S.buildStreamHandlers(streamState, text),
          ChatState.streamController.signal
        );
        await refreshGuestQuota();
	        // 额度不足时温和提醒登录
	        if (ChatState.guestQuota && ChatState.guestQuota.remaining_percent > 0 && ChatState.guestQuota.remaining_percent <= 20) {
	          if (!ChatState._guestQuotaWarnedLow) {
	            ChatState._guestQuotaWarnedLow = true;
	            UI.toast('今天的免费额度不多了，登录后可以无限畅聊', 'info', 3500);
	          }
	        }

      } else {
        await API.streamMessage(
          { character_id: ChatState.currentChar.id, message: text },
          S.buildStreamHandlers(streamState, text, { loggedIn: true }),
          ChatState.streamController.signal
        );
      }
    } catch (err) { await handleSendFailure(err, text); }
    finally { R.removeTyping(); setSending(false); }
  }

  function toggleStatusPanel() { ChatStatusPanel.toggle(); }

  /** 后台异步将游客聊天历史持久化到用户账号 */
  async function _persistGuestHistory(charId, historyMessages) {
    try {
      const payload = {
        character_id: charId,
        messages: historyMessages.filter(function(m) { return m.role === 'user' || m.role === 'assistant'; }),
      };
      if (!payload.messages.length) return;
      await API.mergeGuestHistory(payload);
    } catch (_) { /* 静默失败，不影响主流程 */ }
  }

  /* ── 公开 API ────────────────────────────────────────── */
  return {
    enterChat, send, toggleStatusPanel,
    regenerateMessage: Actions.regenerateMessage,
    continueMessage: Actions.continueMessage,
    refreshCurrentCharacterProfile, applyCharacterProfile, clearCurrentChat,
    getDisplayMeta,
    renderGuestQuotaBar, refreshGuestQuota,
    get currentChar() { return ChatState.currentChar; },
    get history() { return ChatState.history; },
  };
})();
