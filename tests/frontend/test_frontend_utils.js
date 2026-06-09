/**
 * 前端 JS 逻辑单元测试
 *
 * 覆盖范围：
 *   - utils.js: escapeHtml, formatTime, formatDate, formatHistoryTime
 *   - api.js: SSE 事件解析逻辑（从 streamMessageToUrl 提取）
 *
 * 运行方式：node tests/frontend/test_frontend_utils.js
 */

const assert = require('assert');

function formatTime(date) {
    const h = String(date.getHours()).padStart(2, '0');
    const m = String(date.getMinutes()).padStart(2, '0');
    return `${h}:${m}`;
}

function formatDate(date) {
    const days = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
    return `${date.getMonth() + 1}月${date.getDate()}日 ${days[date.getDay()]}`;
}

function formatHistoryTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '时间未知';
    return `${formatDate(date)} ${formatTime(date)}`;
}

function createRetryButton(row, retryText, deps = {}) {
    return {
        className: 'retry-btn',
        textContent: '🔄 重新发送',
        click() {
            (deps.retryMessage || retryMessage)(row, retryText);
        },
    };
}

function retryMessage(row, retryText, deps = {}) {
    row.remove();
    const input = (deps.getElementById || (() => ({ value: '' })))('chat-input');
    input.value = retryText;
    (deps.send || (() => {}))();
    return input;
}

function appendHeaderSign(signEl, text = '', deps = {}) {
    signEl.innerHTML = '';
    const onlineDot = (deps.createSpan || (() => ({ className: '' })))();
    onlineDot.className = 'online-dot';
    signEl.appendChild(onlineDot);
    signEl.appendChild((deps.createTextNode || ((value) => ({ textContent: value })))(text));
    return signEl;
}

function formatSmartTime(value, nowValue = new Date()) {
    const now = new Date(nowValue);
    const d = new Date(value);
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    const timeStr = `${h}:${m}`;
    if (d.toDateString() === now.toDateString()) return timeStr;
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    if (d.toDateString() === yesterday.toDateString()) return `昨天 ${timeStr}`;
    return `${d.getMonth() + 1}月${d.getDate()}日 ${timeStr}`;
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

function parseSSEBuffer(buffer) {
    const blocks = buffer.split('\n\n');
    const lastBlock = blocks.pop() || '';
    const events = [];

    for (const block of blocks) {
        if (!block.trim()) continue;
        const lines = block.split('\n');
        let event = 'message';
        let dataLine = '';
        for (const line of lines) {
            if (line.startsWith('event: ')) event = line.slice(7).trim();
            if (line.startsWith('data: ')) dataLine += line.slice(6);
        }
        if (!dataLine) continue;
        try {
            events.push({ event, data: JSON.parse(dataLine) });
        } catch (_) {}
    }

    return { events, remaining: lastBlock };
}

function fillTypingBubble(bubble) {
    bubble.innerHTML = `
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
    `;
    return bubble;
}

function createStreamState() {
    return {
        bubbleEl: null,
        actionBtnsEl: null,
        streamRowEl: null,
        aiText: '',
    };
}

function createMessageRow(roleClass, messageId = null) {
    const row = {
        className: `msg-row ${roleClass}`,
        dataset: {},
    };
    return assignMessageId(row, messageId);
}

function assignMessageId(target, messageId = null) {
    if (target && messageId) target.dataset.messageId = messageId;
    return target;
}

function createAssistantHistoryEntry(content, messageId = null, createdAt = 'now') {
    return {
        role: 'assistant',
        content,
        created_at: createdAt,
        ...(messageId ? { message_id: messageId } : {}),
    };
}

function getHistoryMessageId(item = {}) {
    return item.message_id || null;
}

function createMessageBubble(roleClass, text = '') {
    return {
        className: `msg-bubble ${roleClass}`,
        textContent: text,
    };
}

function normalizeRenderedText(text) {
    return String(text).replace(/\n{2,}/g, '\n').trim();
}

function appendTextLines(el, lines, deps = {}) {
    lines.forEach((line, i) => {
        el.appendChild((deps.createTextNode || ((value) => ({ type: 'text', textContent: value })))(line));
        if (i < lines.length - 1) {
            el.appendChild((deps.createBr || (() => ({ tagName: 'BR' })))());
        }
    });
    return el;
}

function resolveDisplayText(text, isAssistant = false, deps = {}) {
    if (!isAssistant) return text;
    const stripStatusBlock = deps.stripStatusBlock || ((value) => ({ cleanText: value, statusRaw: null }));
    const renderStatusPanel = deps.renderStatusPanel || (() => {});
    const { cleanText, statusRaw } = stripStatusBlock(text);
    if (statusRaw !== null) {
        renderStatusPanel(statusRaw);
    }
    return cleanText;
}

function flashElementClass(el, className, delay = 1800, deps = {}) {
    if (!el) return null;
    el.classList.add(className);
    (deps.setTimeout || ((fn) => fn()))(() => el.classList.remove(className), delay);
    return el;
}

function renderMessageBubble(bubbleEl, text, isAssistant = false, renderTextWithLineBreaks = (el, value, assistant) => {
    el.rendered = { value, assistant };
}) {
    renderTextWithLineBreaks(bubbleEl, text, isAssistant);
    return bubbleEl;
}

function appendPlainBubble(row, bubble) {
    row.children = row.children || [];
    row.children.push(bubble);
    return bubble;
}

function appendAssistantBubble(row, bubble, actionBtns = null, appendMessageBody = (rowEl, bubbleEl, actionBtnsEl = null) => {
    rowEl.body = { bubbleEl, actionBtnsEl };
}) {
    appendMessageBody(row, bubble, actionBtns);
    return bubble;
}

function createAssistantActionButtons(row = null, bubble = null, messageId = null, hiddenActions = false, createMessageActionButtons = () => ({ id: 'actions', hiddenActions }), bindMessageActionButtons = () => {}) {
    const actionBtns = createMessageActionButtons(hiddenActions);
    if (messageId) bindMessageActionButtons(actionBtns, row, bubble, messageId);
    return actionBtns;
}

function mountAssistantBubble(row, bubble, messageId = null, createAssistantActionButtonsImpl = createAssistantActionButtons, appendAssistantBubbleImpl = appendAssistantBubble) {
    const actionBtns = messageId ? createAssistantActionButtonsImpl(row, bubble, messageId) : null;
    appendAssistantBubbleImpl(row, bubble, actionBtns);
    return actionBtns;
}

function appendBubbleContent(row, bubble, isAi, messageId, mountAssistantBubbleImpl = mountAssistantBubble, appendPlainBubbleImpl = appendPlainBubble) {
    if (isAi) {
        mountAssistantBubbleImpl(row, bubble, messageId);
        return;
    }
    appendPlainBubbleImpl(row, bubble);
}

function shouldShowTime(timestamp, lastMsgTimestamp = 0) {
    if (!lastMsgTimestamp) return true;
    const gap = Math.abs(timestamp - lastMsgTimestamp);
    return gap >= 5 * 60 * 1000;
}

function appendMessageTime(container, date, formatSmartTimeImpl = formatSmartTime) {
    const timeEl = {
        className: 'msg-time',
        textContent: formatSmartTimeImpl(date),
    };
    if (typeof container.appendChild === 'function') {
        container.appendChild(timeEl);
    }
    return timeEl;
}

function appendDividerNode(text, container = null) {
    const node = {
        className: 'date-divider',
        textContent: text,
    };
    if (typeof container?.appendChild === 'function') {
        container.appendChild(node);
    }
    return node;
}

function appendDateDivider(container, formatDateImpl = formatDate, nowValue = new Date()) {
    return appendDividerNode(formatDateImpl(new Date(nowValue)), container);
}

function appendLoadingHint(text, container) {
    return appendDividerNode(text, container);
}

function fillErrorBubble(bubble, text, row, retryText = null, deps = {}) {
    bubble.innerHTML = `⚠ ${(deps.escapeHtml || escapeHtml)(text)}`;
    if (!retryText) return bubble;
    const btn = createRetryButton(row, retryText, { retryMessage: deps.retryMessage });
    bubble.appendChild((deps.createBr || (() => ({ tagName: 'BR' })))());
    bubble.appendChild(btn);
    return bubble;
}

function getMessageActionButtons(rowEl) {
    return {
        regenerate: rowEl?.querySelector('.regenerate-btn') || null,
        continue: rowEl?.querySelector('.continue-btn') || null,
        actions: rowEl?.querySelector('.msg-action-btns') || null,
    };
}

function beginMessageAction(rowEl, { loading = null, showTypingBubble = false, hideActions = false } = {}, deps = {}) {
    const buttons = (deps.getMessageActionButtons || getMessageActionButtons)(rowEl);
    (deps.setSending || (() => {}))(true);
    if (showTypingBubble) {
        (deps.showTyping || (() => {}))();
    }
    (deps.abortStream || (() => {}))();
    if (deps.setController) {
        deps.setController({});
    }

    if (loading === 'regenerate') {
        (deps.setButtonLoading || (() => {}))(buttons.regenerate, true, true);
        (deps.setButtonLoading || (() => {}))(buttons.continue, true);
    } else if (loading === 'continue') {
        (deps.setButtonLoading || (() => {}))(buttons.regenerate, true);
        (deps.setButtonLoading || (() => {}))(buttons.continue, true, true);
    }

    if (hideActions) {
        (deps.setActionButtonsVisible || (() => {}))(buttons.actions, false);
    }

    return buttons;
}

function completeMessageAction(buttons = {}, { loading = null, restoreActions = false } = {}, deps = {}) {
    if (loading === 'regenerate') {
        (deps.setButtonLoading || (() => {}))(buttons.regenerate, false, false);
        (deps.setButtonLoading || (() => {}))(buttons.continue, false);
    } else if (loading === 'continue') {
        (deps.setButtonLoading || (() => {}))(buttons.regenerate, false);
        (deps.setButtonLoading || (() => {}))(buttons.continue, false, false);
    }

    if (restoreActions) {
        (deps.setActionButtonsVisible || (() => {}))(buttons.actions, true);
    }

    (deps.removeTyping || (() => {}))();
    (deps.setSending || (() => {}))(false);
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

function cleanupContinuationFailure(newRowEl, originalButtons, message, deps = {}) {
    (deps.removeTyping || (() => {}))();
    (deps.removeRowIfPresent || (() => {}))(newRowEl);
    (deps.toast || (() => {}))(message, 'warn', 3000);
    (deps.setActionButtonsVisible || (() => {}))(originalButtons?.actions, true);
}

function createNodeRecorder() {
    return {
        nodes: [],
        appendChild(node) {
            this.nodes.push(node);
        },
    };
}

function createClassListRecorder() {
    const classes = new Set();
    return {
        add(name) {
            classes.add(name);
        },
        remove(name) {
            classes.delete(name);
        },
        has(name) {
            return classes.has(name);
        },
    };
}

function renderPager(container, page, totalPages, total, onPageChange) {
    if (!container) return;
    const pages = [];
    for (let i = 1; i <= Math.min(totalPages, 7); i++) pages.push(i);
    if (!container.dataset.pagerBound) {
        container.addEventListener('click', (event) => {
            const btn = event.target.closest('.pager-btn[data-page]');
            if (!btn || btn.disabled) return;
            event.preventDefault();
            const nextPage = parseInt(btn.dataset.page, 10);
            if (Number.isNaN(nextPage)) return;
            onPageChange(nextPage);
        });
        container.dataset.pagerBound = '1';
    }

    const makeBtn = (label, targetPage, disabled, active = false) => {
        const safeTarget = Math.min(totalPages, Math.max(1, targetPage));
        return `<button class="pager-btn ${active ? 'active' : ''}" data-page="${safeTarget}" ${disabled ? 'disabled' : ''}>${label}</button>`;
    };

    container.innerHTML = `
    <div class="pager-info">第 ${page} / ${totalPages} 页，共 ${total} 条</div>
    <div class="pager-controls">
      ${makeBtn('«', 1, page === 1)}
      ${makeBtn('‹', page - 1, page === 1)}
      ${pages.map(p => makeBtn(String(p), p, false, p === page)).join('')}
      ${makeBtn('›', page + 1, page >= totalPages)}
      ${makeBtn('»', totalPages, page >= totalPages)}
    </div>`;
}

function createPagerTestContainer() {
    const listeners = {};
    return {
        dataset: {},
        innerHTML: '',
        addEventListener(type, handler) {
            listeners[type] = listeners[type] || [];
            listeners[type].push(handler);
        },
        dispatch(type, event) {
            (listeners[type] || []).forEach((handler) => handler(event));
        },
        getListenerCount(type) {
            return (listeners[type] || []).length;
        },
    };
}

function createPagerButton(page, { disabled = false, matched = true } = {}) {
    return {
        disabled,
        dataset: { page: String(page) },
        closest(selector) {
            if (!matched || selector !== '.pager-btn[data-page]') return null;
            return this;
        },
    };
}

function buildActionHandlers(characterHandlers, advancedHandlers, membershipHandlers, dashboardHandlers) {
    return {
        ...characterHandlers,
        ...advancedHandlers,
        ...membershipHandlers,
        ...dashboardHandlers,
    };
}

function handlePrimaryAction(actionHandlers, action, trigger) {
    const handler = actionHandlers[action];
    if (!handler) return false;
    handler(trigger);
    return true;
}

function dispatchDelegatedClick(handlePrimaryActionImpl, actionHandlers, event) {
    const actionTrigger = event.target.closest('[data-action]');
    if (!actionTrigger) return false;
    const action = actionTrigger.dataset.action;
    const handled = handlePrimaryActionImpl(actionHandlers, action, actionTrigger);
    if (!handled) return false;
    event.preventDefault();
    return true;
}

(function runTests() {
    const date = new Date('2026-01-02T03:04:00');
    assert.strictEqual(formatTime(date), '03:04');
    assert.strictEqual(formatDate(new Date('2026-01-02T03:04:00')), '1月2日 周五');
    assert.strictEqual(formatHistoryTime('2026-01-02T03:04:00'), '1月2日 周五 03:04');
    assert.strictEqual(formatHistoryTime('invalid'), '时间未知');

    const pagerContainer = createPagerTestContainer();
    const pageChanges = [];
    renderPager(pagerContainer, 2, 10, 95, (nextPage) => pageChanges.push(nextPage));
    assert.strictEqual(pagerContainer.dataset.pagerBound, '1');
    assert.ok(pagerContainer.innerHTML.includes('第 2 / 10 页，共 95 条'));
    assert.ok(pagerContainer.innerHTML.includes('data-page="1"'));
    assert.ok(pagerContainer.innerHTML.includes('data-page="7"'));
    assert.ok(!pagerContainer.innerHTML.includes('data-page="8"'));

    renderPager(pagerContainer, 3, 10, 95, (nextPage) => pageChanges.push(nextPage));
    assert.strictEqual(pagerContainer.getListenerCount('click'), 1);

    let prevented = false;
    pagerContainer.dispatch('click', {
        target: createPagerButton(5),
        preventDefault() {
            prevented = true;
        },
    });
    assert.ok(prevented);
    assert.deepStrictEqual(pageChanges, [5]);

    pagerContainer.dispatch('click', {
        target: createPagerButton('bad'),
        preventDefault() {},
    });
    pagerContainer.dispatch('click', {
        target: createPagerButton(6, { disabled: true }),
        preventDefault() {},
    });
    pagerContainer.dispatch('click', {
        target: createPagerButton(6, { matched: false }),
        preventDefault() {},
    });
    assert.deepStrictEqual(pageChanges, [5]);

    const calls = [];
    const handlers = buildActionHandlers(
        {
            'save-char': () => calls.push('save-char'),
            'open-user-detail': () => calls.push('character-open-user-detail'),
            'select-char': (trigger) => {
                if (trigger.dataset.charId) {
                    calls.push(`select-char:${trigger.dataset.charId}`);
                }
            },
        },
        {
            'save-memory': () => calls.push('save-memory'),
        },
        {
            'open-user-detail': (trigger) => calls.push(`membership-open-user-detail:${trigger.dataset.userId}`),
            'open-order-detail': (trigger) => calls.push(`open-order-detail:${trigger.dataset.orderId || ''}`),
        },
        {
            'admin-reload': () => calls.push('admin-reload'),
        }
    );
    assert.ok(handlePrimaryAction(handlers, 'save-char', {}));
    assert.ok(handlePrimaryAction(handlers, 'save-memory', {}));
    assert.ok(handlePrimaryAction(handlers, 'open-user-detail', { dataset: { userId: '42' } }));
    assert.ok(handlePrimaryAction(handlers, 'select-char', { dataset: { charId: 'char_a' } }));
    assert.ok(handlePrimaryAction(handlers, 'select-char', { dataset: {} }));
    assert.ok(handlePrimaryAction(handlers, 'open-order-detail', { dataset: { orderId: 'od_9' } }));
    assert.ok(handlePrimaryAction(handlers, 'admin-reload', {}));
    assert.strictEqual(handlePrimaryAction(handlers, 'not-exists', {}), false);
    assert.deepStrictEqual(calls, [
        'save-char',
        'save-memory',
        'membership-open-user-detail:42',
        'select-char:char_a',
        'open-order-detail:od_9',
        'admin-reload',
    ]);

    let delegatedPrevented = false;
    const delegatedEvent = {
        target: {
            closest(selector) {
                if (selector !== '[data-action]') return null;
                return { dataset: { action: 'open-order-detail', orderId: 'od_dynamic' } };
            },
        },
        preventDefault() {
            delegatedPrevented = true;
        },
    };
    assert.strictEqual(dispatchDelegatedClick(handlePrimaryAction, handlers, delegatedEvent), true);
    assert.ok(delegatedPrevented);

    delegatedPrevented = false;
    const notHandledEvent = {
        target: {
            closest() {
                return { dataset: { action: 'unknown-action' } };
            },
        },
        preventDefault() {
            delegatedPrevented = true;
        },
    };
    assert.strictEqual(dispatchDelegatedClick(handlePrimaryAction, handlers, notHandledEvent), false);
    assert.ok(!delegatedPrevented);
    assert.deepStrictEqual(calls.slice(-1), ['open-order-detail:od_dynamic']);

    assert.strictEqual(
        escapeHtml(`<div>"x" & 'y'\n</div>`),
        '&lt;div&gt;&quot;x&quot; &amp; &#39;y&#39;<br/>&lt;/div&gt;'
    );

    const parsed = parseSSEBuffer(
        'event: delta\ndata: {"text":"hello"}\n\n' +
        'event: done\ndata: {"ok":true}\n\n' +
        'event: incomplete\ndata: {"x":1}'
    );
    assert.deepStrictEqual(parsed.events, [
        { event: 'delta', data: { text: 'hello' } },
        { event: 'done', data: { ok: true } },
    ]);
    assert.strictEqual(parsed.remaining, 'event: incomplete\ndata: {"x":1}');

    const bubble = { innerHTML: '' };
    fillTypingBubble(bubble);
    assert.ok(bubble.innerHTML.includes('typing-dot'));

    const streamState = createStreamState();
    assert.deepStrictEqual(streamState, {
        bubbleEl: null,
        actionBtnsEl: null,
        streamRowEl: null,
        aiText: '',
    });

    const rowWithId = createMessageRow('assistant', 'msg-1');
    assert.strictEqual(rowWithId.className, 'msg-row assistant');
    assert.strictEqual(rowWithId.dataset.messageId, 'msg-1');

    const rowWithoutId = createMessageRow('user');
    assert.deepStrictEqual(rowWithoutId.dataset, {});

    const historyEntry = createAssistantHistoryEntry('hello', 'mid-1', '2026-01-01T10:00:00Z');
    assert.deepStrictEqual(historyEntry, {
        role: 'assistant',
        content: 'hello',
        created_at: '2026-01-01T10:00:00Z',
        message_id: 'mid-1',
    });

    const historyEntryWithoutId = createAssistantHistoryEntry('hello');
    assert.deepStrictEqual(historyEntryWithoutId, {
        role: 'assistant',
        content: 'hello',
        created_at: 'now',
    });

    assert.strictEqual(getHistoryMessageId({ role: 'assistant', message_id: 'mid-2' }), 'mid-2');
    assert.strictEqual(getHistoryMessageId({ role: 'user' }), null);

    const bubbleNode = createMessageBubble('ai', '你好');
    assert.deepStrictEqual(bubbleNode, {
        className: 'msg-bubble ai',
        textContent: '你好',
    });

    assert.strictEqual(normalizeRenderedText('\nhello\n\nworld\n'), 'hello\nworld');

    const textContainer = createNodeRecorder();
    appendTextLines(textContainer, ['第一行', '第二行']);
    assert.deepStrictEqual(textContainer.nodes, [
        { type: 'text', textContent: '第一行' },
        { tagName: 'BR' },
        { type: 'text', textContent: '第二行' },
    ]);

    let renderedStatus = null;
    const cleanText = resolveDisplayText('正文', true, {
        stripStatusBlock(value) {
            return { cleanText: `${value}-clean`, statusRaw: 'mood=happy' };
        },
        renderStatusPanel(value) {
            renderedStatus = value;
        },
    });
    assert.strictEqual(cleanText, '正文-clean');
    assert.strictEqual(renderedStatus, 'mood=happy');
    assert.strictEqual(resolveDisplayText('用户消息', false), '用户消息');

    const classList = createClassListRecorder();
    const flashTarget = { classList };
    let timerDelay = null;
    flashElementClass(flashTarget, 'copied', 300, {
        setTimeout(fn, delay) {
            timerDelay = delay;
            assert.ok(classList.has('copied'));
            fn();
        },
    });
    assert.strictEqual(timerDelay, 300);
    assert.ok(!classList.has('copied'));
    assert.strictEqual(flashElementClass(null, 'copied'), null);

    const renderedBubble = {};
    renderMessageBubble(renderedBubble, 'test', true);
    assert.deepStrictEqual(renderedBubble.rendered, { value: 'test', assistant: true });

    const plainRow = {};
    appendPlainBubble(plainRow, { id: 'bubble-1' });
    assert.deepStrictEqual(plainRow.children, [{ id: 'bubble-1' }]);

    const assistantRow = {};
    appendAssistantBubble(assistantRow, { id: 'bubble-2' }, { id: 'actions' });
    assert.deepStrictEqual(assistantRow.body, {
        bubbleEl: { id: 'bubble-2' },
        actionBtnsEl: { id: 'actions' },
    });

    let boundArgs = null;
    const actionBtns = createAssistantActionButtons({}, {}, 'msg-2', true,
        (hiddenActions) => ({ hiddenActions }),
        (...args) => {
            boundArgs = args;
        }
    );
    assert.deepStrictEqual(actionBtns, { hiddenActions: true });
    assert.strictEqual(boundArgs[3], 'msg-2');

    let mountedArgs = null;
    const mountResult = mountAssistantBubble(
        { id: 'row' },
        { id: 'bubble' },
        'msg-3',
        () => ({ id: 'actions-2' }),
        (row, bubbleArg, actionBtnsArg) => {
            mountedArgs = { row, bubble: bubbleArg, actionBtns: actionBtnsArg };
        }
    );
    assert.deepStrictEqual(mountResult, { id: 'actions-2' });
    assert.deepStrictEqual(mountedArgs, {
        row: { id: 'row' },
        bubble: { id: 'bubble' },
        actionBtns: { id: 'actions-2' },
    });

    let appendAssistantCalled = false;
    let appendPlainCalled = false;
    appendBubbleContent({}, {}, true, 'msg-4', () => {
        appendAssistantCalled = true;
    }, () => {
        appendPlainCalled = true;
    });
    assert.ok(appendAssistantCalled);
    assert.ok(!appendPlainCalled);

    appendAssistantCalled = false;
    appendPlainCalled = false;
    appendBubbleContent({}, {}, false, null, () => {
        appendAssistantCalled = true;
    }, () => {
        appendPlainCalled = true;
    });
    assert.ok(!appendAssistantCalled);
    assert.ok(appendPlainCalled);

    assert.strictEqual(shouldShowTime(Date.parse('2026-01-02T10:00:00Z'), 0), true);
    assert.strictEqual(
        shouldShowTime(Date.parse('2026-01-02T10:04:59Z'), Date.parse('2026-01-02T10:00:00Z')),
        false
    );
    assert.strictEqual(
        shouldShowTime(Date.parse('2026-01-02T10:05:00Z'), Date.parse('2026-01-02T10:00:00Z')),
        true
    );

    const timeContainer = createNodeRecorder();
    const timeNode = appendMessageTime(timeContainer, '2026-01-02T03:04:00', () => '03:04');
    assert.strictEqual(timeNode.textContent, '03:04');
    assert.deepStrictEqual(timeContainer.nodes, [timeNode]);

    const dividerContainer = createNodeRecorder();
    const divider = appendDividerNode('今天', dividerContainer);
    assert.deepStrictEqual(divider, { className: 'date-divider', textContent: '今天' });
    assert.deepStrictEqual(dividerContainer.nodes, [divider]);

    const dateDivider = appendDateDivider(dividerContainer, () => '1月2日 周五', '2026-01-02T03:04:00');
    assert.strictEqual(dateDivider.textContent, '1月2日 周五');

    const loadingHint = appendLoadingHint('加载中...', dividerContainer);
    assert.strictEqual(loadingHint.textContent, '加载中...');

    const retryCalls = [];
    const errorBubble = {
        innerHTML: '',
        children: [],
        appendChild(node) {
            this.children.push(node);
        },
    };
    fillErrorBubble(errorBubble, '<失败>', { id: 1 }, '重试文本', {
        escapeHtml,
        retryMessage(row, text) {
            retryCalls.push({ row, text });
        },
        createBr() {
            return { tagName: 'BR' };
        },
    });
    assert.strictEqual(errorBubble.innerHTML, '⚠ &lt;失败&gt;');
    assert.strictEqual(errorBubble.children.length, 2);
    errorBubble.children[1].click();
    assert.deepStrictEqual(retryCalls, [{ row: { id: 1 }, text: '重试文本' }]);

    const row = {
        removed: false,
        remove() {
            this.removed = true;
        },
    };
    let sendCalled = false;
    const input = { value: '' };
    const returnedInput = retryMessage(row, '重新输入', {
        getElementById(id) {
            assert.strictEqual(id, 'chat-input');
            return input;
        },
        send() {
            sendCalled = true;
        },
    });
    assert.strictEqual(returnedInput, input);
    assert.strictEqual(input.value, '重新输入');
    assert.ok(row.removed);
    assert.ok(sendCalled);

    const retryBtn = createRetryButton({ id: 9 }, '再次发送', {
        retryMessage(r, t) {
            retryCalls.push({ row: r, text: t });
        },
    });
    retryBtn.click();
    assert.deepStrictEqual(retryCalls[1], { row: { id: 9 }, text: '再次发送' });

    const signEl = {
        innerHTML: 'old',
        children: [],
        appendChild(node) {
            this.children.push(node);
        },
    };
    appendHeaderSign(signEl, '在线', {
        createSpan() {
            return { className: '' };
        },
        createTextNode(value) {
            return { textContent: value };
        },
    });
    assert.strictEqual(signEl.innerHTML, '');
    assert.strictEqual(signEl.children[0].className, 'online-dot');
    assert.strictEqual(signEl.children[1].textContent, '在线');

    assert.strictEqual(formatSmartTime('2026-01-02T03:04:00', '2026-01-02T10:00:00'), '03:04');
    assert.strictEqual(formatSmartTime('2026-01-01T03:04:00', '2026-01-02T10:00:00'), '昨天 03:04');
    assert.strictEqual(formatSmartTime('2025-12-31T03:04:00', '2026-01-02T10:00:00'), '12月31日 03:04');

    const buttons = getMessageActionButtons({
        querySelector(selector) {
            return { selector };
        },
    });
    assert.deepStrictEqual(buttons, {
        regenerate: { selector: '.regenerate-btn' },
        continue: { selector: '.continue-btn' },
        actions: { selector: '.msg-action-btns' },
    });

    const actionCalls = [];
    const beginButtons = beginMessageAction(
        { id: 'row-1' },
        { loading: 'continue', showTypingBubble: true, hideActions: true },
        {
            getMessageActionButtons() {
                return {
                    regenerate: { id: 'regen' },
                    continue: { id: 'continue' },
                    actions: { id: 'actions' },
                };
            },
            setSending(value) {
                actionCalls.push(['setSending', value]);
            },
            showTyping() {
                actionCalls.push(['showTyping']);
            },
            abortStream() {
                actionCalls.push(['abortStream']);
            },
            setController(value) {
                actionCalls.push(['setController', typeof value]);
            },
            setButtonLoading(button, disabled, loading) {
                actionCalls.push(['setButtonLoading', button.id, disabled, loading ?? false]);
            },
            setActionButtonsVisible(button, visible) {
                actionCalls.push(['setActionButtonsVisible', button.id, visible]);
            },
        }
    );
    assert.deepStrictEqual(beginButtons, {
        regenerate: { id: 'regen' },
        continue: { id: 'continue' },
        actions: { id: 'actions' },
    });
    assert.deepStrictEqual(actionCalls, [
        ['setSending', true],
        ['showTyping'],
        ['abortStream'],
        ['setController', 'object'],
        ['setButtonLoading', 'regen', true, false],
        ['setButtonLoading', 'continue', true, true],
        ['setActionButtonsVisible', 'actions', false],
    ]);

    const completeCalls = [];
    completeMessageAction(
        beginButtons,
        { loading: 'regenerate', restoreActions: true },
        {
            setButtonLoading(button, disabled, loading) {
                completeCalls.push(['setButtonLoading', button.id, disabled, loading ?? false]);
            },
            setActionButtonsVisible(button, visible) {
                completeCalls.push(['setActionButtonsVisible', button.id, visible]);
            },
            removeTyping() {
                completeCalls.push(['removeTyping']);
            },
            setSending(value) {
                completeCalls.push(['setSending', value]);
            },
        }
    );
    assert.deepStrictEqual(completeCalls, [
        ['setButtonLoading', 'regen', false, false],
        ['setButtonLoading', 'continue', false, false],
        ['setActionButtonsVisible', 'actions', true],
        ['removeTyping'],
        ['setSending', false],
    ]);

    assert.deepStrictEqual(
        resolveContinuationResult('原回复', '追加', { appended_text: '最终追加', message_id: 'msg-next' }, 'msg-old'),
        {
            finalAppended: '最终追加',
            nextMessageId: 'msg-next',
            fullText: '原回复最终追加',
        }
    );
    assert.deepStrictEqual(
        resolveContinuationResult('', '追加', null, 'msg-old'),
        {
            finalAppended: '追加',
            nextMessageId: 'msg-old',
            fullText: '追加',
        }
    );

    const cleanupCalls = [];
    cleanupContinuationFailure(
        { id: 'temp-row' },
        { actions: { id: 'origin-actions' } },
        '继续生成失败',
        {
            removeTyping() {
                cleanupCalls.push(['removeTyping']);
            },
            removeRowIfPresent(row) {
                cleanupCalls.push(['removeRowIfPresent', row.id]);
            },
            toast(message, level, duration) {
                cleanupCalls.push(['toast', message, level, duration]);
            },
            setActionButtonsVisible(button, visible) {
                cleanupCalls.push(['setActionButtonsVisible', button.id, visible]);
            },
        }
    );
    assert.deepStrictEqual(cleanupCalls, [
        ['removeTyping'],
        ['removeRowIfPresent', 'temp-row'],
        ['toast', '继续生成失败', 'warn', 3000],
        ['setActionButtonsVisible', 'origin-actions', true],
    ]);

    console.log('✅ 前端 JS 逻辑测试全部通过');
})();
