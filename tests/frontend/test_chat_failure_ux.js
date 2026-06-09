/**
 * 对话失败体验回归测试
 *
 * 运行方式：node tests/test_chat_failure_ux.js
 */

const assert = require('assert');

function handleSSEEvent(event, payloadData, handlers = {}) {
    if (event === 'chunk' && handlers.onChunk) handlers.onChunk(payloadData.text || '');
    if (event === 'done' && handlers.onDone) handlers.onDone(payloadData);
    if (event === 'error') {
        if (handlers.onError) handlers.onError(payloadData);
        const err = new Error(payloadData?.message || '流式请求失败');
        err.status = 'sse_error';
        throw err;
    }
}

function removeLatestUserMessage(text, deps = {}) {
    const box = (deps.getElementById || (() => null))('chat-messages');
    if (!box) return false;
    const rows = Array.from(box.querySelectorAll('.msg-row.user'));
    const target = rows[rows.length - 1];
    if (!target) return false;
    const bubble = target.querySelector('.msg-bubble.user');
    if (text != null && bubble && bubble.textContent !== text) return false;
    target.remove();
    return true;
}

function isStateBarHidden(currentChar = null, lastState = null) {
    if (lastState && lastState.show_bar === false) return true;
    if (currentChar) {
        if (currentChar.affection_enabled === 0 || currentChar.affection_enabled === '0') return true;
        try {
            const rules = JSON.parse(currentChar.affection_rules_json || '{}');
            return rules.show_bar === false;
        } catch (_) {}
    }
    return false;
}

function cleanupStreamError(streamState, deps = {}) {
    (deps.cleanupStreamState || (() => {}))(streamState);
}

function handleStreamError(streamState, payload, fallbackMessage = '网络波动，请稍后再试', deps = {}) {
    cleanupStreamError(streamState, deps);
    (deps.toast || (() => {}))(payload?.message || fallbackMessage, 'warn', 3000);
}

async function handleSendFailureMessage(err, deps = {}) {
    let specificToastShown = false;
    if (!deps.isLoggedIn()) {
        await deps.refreshGuestQuota();
        if ((err.message || '').includes('额度已用完')) {
            deps.toast('今日游客体验额度已用完，登录后可继续聊天', 'warn', 3200);
            specificToastShown = true;
            deps.openLoginLater();
        } else if ((err.message || '').includes('发送太快')) {
            deps.toast('发送太快了，请稍后再试', 'warn', 2500);
            specificToastShown = true;
        }
    }
    if (!specificToastShown) deps.toast(`发送失败：${err.message}`, 'warn', 3000);
}

(function runTests() {
    const sseCalls = [];
    handleSSEEvent('chunk', { text: '片段' }, {
        onChunk(text) {
            sseCalls.push(['chunk', text]);
        },
    });
    handleSSEEvent('done', { reply: '完成' }, {
        onDone(payload) {
            sseCalls.push(['done', payload.reply]);
        },
    });
    assert.throws(
        () => handleSSEEvent('error', { message: '保存失败，请稍后再试' }, {
            onError(payload) {
                sseCalls.push(['error', payload.message]);
            },
        }),
        /保存失败/
    );
    assert.deepStrictEqual(sseCalls, [
        ['chunk', '片段'],
        ['done', '完成'],
        ['error', '保存失败，请稍后再试'],
    ]);

    const removableRows = [
        {
            removed: false,
            querySelector() { return { textContent: '旧消息' }; },
            remove() { this.removed = true; },
        },
        {
            removed: false,
            querySelector() { return { textContent: '刚发送' }; },
            remove() { this.removed = true; },
        },
    ];
    assert.strictEqual(removeLatestUserMessage('刚发送', {
        getElementById(id) {
            assert.strictEqual(id, 'chat-messages');
            return { querySelectorAll: () => removableRows };
        },
    }), true);
    assert.ok(!removableRows[0].removed);
    assert.ok(removableRows[1].removed);

    assert.strictEqual(removeLatestUserMessage('不匹配', {
        getElementById() {
            return { querySelectorAll: () => removableRows };
        },
    }), false);

    assert.strictEqual(isStateBarHidden({ affection_enabled: 0 }, null), true);
    assert.strictEqual(isStateBarHidden({ affection_rules_json: '{"show_bar":false}' }, null), true);
    assert.strictEqual(isStateBarHidden({ affection_enabled: 1, affection_rules_json: '{}' }, null), false);

    const streamErrorCalls = [];
    cleanupStreamError(
        { id: 'stream-state' },
        {
            cleanupStreamState(state) {
                streamErrorCalls.push(['cleanupStreamState', state.id]);
            },
        }
    );
    assert.deepStrictEqual(streamErrorCalls, [['cleanupStreamState', 'stream-state']]);

    handleStreamError(
        { id: 'stream-state-2' },
        { message: '网络波动' },
        'fallback',
        {
            cleanupStreamState(state) {
                streamErrorCalls.push(['cleanupStreamState', state.id]);
            },
            toast(message, level, duration) {
                streamErrorCalls.push(['toast', message, level, duration]);
            },
        }
    );
    assert.deepStrictEqual(streamErrorCalls.slice(1), [
        ['cleanupStreamState', 'stream-state-2'],
        ['toast', '网络波动', 'warn', 3000],
    ]);

    return Promise.resolve().then(async () => {
        const sendFailureToasts = [];
        await handleSendFailureMessage(new Error('今日游客体验额度已用完'), {
            isLoggedIn: () => false,
            refreshGuestQuota: async () => {},
            toast(message, level, duration) {
                sendFailureToasts.push([message, level, duration]);
            },
            openLoginLater() {
                sendFailureToasts.push(['open-login']);
            },
        });
        assert.deepStrictEqual(sendFailureToasts, [
            ['今日游客体验额度已用完，登录后可继续聊天', 'warn', 3200],
            ['open-login'],
        ]);

        await handleSendFailureMessage(new Error('网络波动'), {
            isLoggedIn: () => true,
            refreshGuestQuota: async () => {},
            toast(message, level, duration) {
                sendFailureToasts.push([message, level, duration]);
            },
            openLoginLater() {},
        });
        assert.deepStrictEqual(sendFailureToasts.slice(-1), [
            ['发送失败：网络波动', 'warn', 3000],
        ]);

        console.log('✅ 对话失败体验测试通过');
    });
})();
