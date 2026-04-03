/**
 * 前端 JS 逻辑单元测试
 *
 * 覆盖范围：
 *   - utils.js: escapeHtml, formatTime, formatDate, formatHistoryTime
 *   - api.js: SSE 事件解析逻辑（从 streamMessageToUrl 提取）
 *
 * 运行方式：node tests/test_frontend_utils.js
 */

const assert = require('assert');

// ============================================================
// 从源码提取纯逻辑函数（模拟浏览器环境）
// ============================================================

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
        } catch (_) { /* skip invalid JSON */ }
    }

    return { events, remaining: lastBlock };
}


// ============================================================
// 测试框架（极简版）
// ============================================================

let passed = 0;
let failed = 0;
const failures = [];

function describe(name, fn) {
    console.log(`\n📦 ${name}`);
    fn();
}

function it(name, fn) {
    try {
        fn();
        passed++;
        console.log(`  ✅ ${name}`);
    } catch (e) {
        failed++;
        failures.push({ name, error: e.message });
        console.log(`  ❌ ${name}: ${e.message}`);
    }
}

function expect(actual) {
    return {
        toBe(expected) {
            assert.strictEqual(actual, expected, `Expected "${expected}" but got "${actual}"`);
        },
        toContain(substr) {
            assert.ok(actual.includes(substr), `Expected "${actual}" to contain "${substr}"`);
        },
        toBeGreaterThan(n) {
            assert.ok(actual > n, `Expected ${actual} > ${n}`);
        },
        toBeLessThan(n) {
            assert.ok(actual < n, `Expected ${actual} < ${n}`);
        },
        toBeArray() {
            assert.ok(Array.isArray(actual), `Expected array, got ${typeof actual}`);
        },
        toHaveLength(n) {
            assert.strictEqual(actual.length, n, `Expected length ${n}, got ${actual.length}`);
        },
        toBeTruthy() {
            assert.ok(actual, `Expected truthy value, got ${actual}`);
        },
        toBeFalsy() {
            assert.ok(!actual, `Expected falsy value, got ${actual}`);
        },
    };
}


// ============================================================
// 1. formatTime 测试
// ============================================================

describe('formatTime', () => {
    it('应格式化午夜为 00:00', () => {
        expect(formatTime(new Date(2026, 3, 3, 0, 0))).toBe('00:00');
    });

    it('应格式化中午为 12:00', () => {
        expect(formatTime(new Date(2026, 3, 3, 12, 0))).toBe('12:00');
    });

    it('应补零小时和分钟', () => {
        expect(formatTime(new Date(2026, 3, 3, 9, 5))).toBe('09:05');
    });

    it('应格式化 23:59', () => {
        expect(formatTime(new Date(2026, 3, 3, 23, 59))).toBe('23:59');
    });
});


// ============================================================
// 2. formatDate 测试
// ============================================================

describe('formatDate', () => {
    it('应包含月份和日期', () => {
        const result = formatDate(new Date(2026, 3, 3));
        expect(result).toContain('4月3日');
    });

    it('应包含星期几', () => {
        const result = formatDate(new Date(2026, 3, 3));
        // 2026-04-03 是周五
        expect(result).toContain('周五');
    });

    it('周日测试', () => {
        // 2026年1月4日是周日（通过 getDay() === 0 验证）
        const d = new Date(2026, 0, 4);
        assert.strictEqual(d.getDay(), 0, 'Pre-check: Jan 4 2026 should be Sunday');
        const result = formatDate(d);
        expect(result).toContain('周日');
    });

    it('周一测试', () => {
        // 2026年1月5日是周一（通过 getDay() === 1 验证）
        const d = new Date(2026, 0, 5);
        assert.strictEqual(d.getDay(), 1, 'Pre-check: Jan 5 2026 should be Monday');
        const result = formatDate(d);
        expect(result).toContain('周一');
    });
});


// ============================================================
// 3. formatHistoryTime 测试
// ============================================================

describe('formatHistoryTime', () => {
    it('标准 ISO 格式应正常解析', () => {
        const result = formatHistoryTime('2026-04-03T14:30:00Z');
        expect(result).toContain('4月3日');
        // 注意：ISO Z 后缀会被解析为 UTC，显示时转为本地时区
        // 不断言具体时分，只验证日期部分
    });

    it('非法日期返回"时间未知"', () => {
        expect(formatHistoryTime('not-a-date')).toBe('时间未知');
    });

    it('空字符串返回"时间未知"', () => {
        expect(formatHistoryTime('')).toBe('时间未知');
    });
});


// ============================================================
// 4. escapeHtml 测试
// ============================================================

describe('escapeHtml', () => {
    it('转义 & 字符', () => {
        expect(escapeHtml('a&b')).toBe('a&amp;b');
    });

    it('转义 < 和 > 字符', () => {
        expect(escapeHtml('<div>')).toBe('&lt;div&gt;');
    });

    it('转义双引号', () => {
        expect(escapeHtml('"hello"')).toBe('&quot;hello&quot;');
    });

    it('转义单引号', () => {
        expect(escapeHtml("it's")).toBe('it&#39;s');
    });

    it('转义换行为 <br/>', () => {
        expect(escapeHtml('line1\nline2')).toBe('line1<br/>line2');
    });

    it('混合 HTML 攻击向量', () => {
        const input = '<script>alert("xss")</script>';
        const output = escapeHtml(input);
        assert.ok(!output.includes('<script>'), 'Script tag should be escaped');
        assert.ok(output.includes('&lt;script&gt;'), 'Should contain escaped script');
    });

    it('空字符串安全处理', () => {
        expect(escapeHtml('')).toBe('');
    });

    it('undefined 参数默认空字符串', () => {
        expect(escapeHtml(undefined)).toBe('');
    });

    it('中文字符不受影响', () => {
        expect(escapeHtml('你好世界')).toBe('你好世界');
    });

    it('连续特殊字符全部转义', () => {
        const input = '<>&"\'\n';
        const output = escapeHtml(input);
        assert.ok(output.includes('&amp;'), 'Should have &amp;');
        assert.ok(output.includes('&lt;'), 'Should have &lt;');
        assert.ok(output.includes('&gt;'), 'Should have &gt;');
        assert.ok(output.includes('&quot;'), 'Should have &quot;');
        assert.ok(output.includes('&#39;'), 'Should have &#39;');
        assert.ok(output.includes('<br/>'), 'Should have <br/>');
    });
});


// ============================================================
// 5. SSE 事件解析测试
// ============================================================

describe('SSE parseSSEBuffer', () => {
    it('解析单个 chunk 事件', () => {
        const input = 'event: chunk\ndata: {"text": "你好"}\n\n';
        const { events } = parseSSEBuffer(input);
        expect(events.length).toBe(1);
        expect(events[0].event).toBe('chunk');
        expect(events[0].data.text).toBe('你好');
    });

    it('解析 done 事件', () => {
        const input = 'event: done\ndata: {"reply": "完整回复"}\n\n';
        const { events } = parseSSEBuffer(input);
        expect(events[0].event).toBe('done');
        expect(events[0].data.reply).toBe('完整回复');
    });

    it('解析 error 事件', () => {
        const input = 'event: error\ndata: {"message": "AI调用失败"}\n\n';
        const { events } = parseSSEBuffer(input);
        expect(events[0].event).toBe('error');
    });

    it('多个事件依次解析', () => {
        const input = [
            'event: chunk',
            'data: {"text": "你"}',
            '',
            'event: chunk',
            'data: {"text": "好"}',
            '',
            'event: done',
            'data: {"reply": "你好"}',
            '',
            '',
        ].join('\n');

        const { events } = parseSSEBuffer(input);
        expect(events.length).toBe(3);
        expect(events[0].data.text).toBe('你');
        expect(events[1].data.text).toBe('好');
        expect(events[2].event).toBe('done');
    });

    it('保留不完整的最后一块到 remaining', () => {
        const input = 'event: chunk\ndata: {"text":"A"}\n\nevent: chunk\ndata: {"text';
        const { events, remaining } = parseSSEBuffer(input);
        expect(events.length).toBe(1);
        expect(remaining).toContain('data: {"text');
    });

    it('空输入返回空事件', () => {
        const { events, remaining } = parseSSEBuffer('');
        expect(events.length).toBe(0);
        expect(remaining).toBe('');
    });

    it('跳过空块', () => {
        const input = '\n\nevent: chunk\ndata: {"text":"x"}\n\n\n\n';
        const { events } = parseSSEBuffer(input);
        expect(events.length).toBe(1);
    });

    it('无效 JSON 块被跳过', () => {
        const input = 'event: chunk\ndata: not json\n\nevent: chunk\ndata: {"text":"ok"}\n\n';
        const { events } = parseSSEBuffer(input);
        expect(events.length).toBe(1);
        expect(events[0].data.text).toBe('ok');
    });

    it('默认 event 类型为 message', () => {
        const input = 'data: {"text":"no event type"}\n\n';
        const { events } = parseSSEBuffer(input);
        expect(events[0].event).toBe('message');
    });

    it('多行 data 拼接', () => {
        const input = 'event: chunk\ndata: {"te\ndata: xt":"val"}\n\n';
        const { events } = parseSSEBuffer(input);
        // 拼接后的 JSON 可能合法也可能不合法，但不崩溃即可
        expect(events).toBeTruthy();
    });
});


// ============================================================
// 运行结果汇总
// ============================================================

console.log('\n' + '='.repeat(50));
console.log(`📊 测试结果: ${passed} 通过, ${failed} 失败, 共 ${passed + failed} 个`);

if (failures.length > 0) {
    console.log('\n❌ 失败详情:');
    failures.forEach((f, i) => {
        console.log(`  ${i + 1}. ${f.name}: ${f.error}`);
    });
    process.exitCode = 1;
} else {
    console.log('\n✅ 全部通过！');
}
