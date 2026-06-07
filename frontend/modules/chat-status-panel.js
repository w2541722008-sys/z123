/**
 * 角色状态面板 — 解析并渲染 AI 输出中的状态栏块
 *
 * 职责：
 * - 从 AI 回复文本中剥离状态栏内容（支持 XML、Markdown、分割线等多种格式）
 * - 解析状态栏字段并渲染到 DOM
 * - 提供折叠/展开/重置交互
 */
const ChatStatusPanel = (() => {
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
    const hrRe = /\n---+\n([\s\S]*)$/;
    const hrMatch = text.match(hrRe);
    if (hrMatch) {
      const afterHr = hrMatch[1].trim();
      if (/状态栏|状态信息|状态\s*[\|｜]|心情[：:]/i.test(afterHr)) {
        const statusRaw = afterHr;
        const cleanText = text.slice(0, text.lastIndexOf('\n---')).trim();
        return { cleanText, statusRaw };
      }
    }

    // 格式③：【状态栏】开头（白邬风格，可能在正文中间或末尾）
    const bracketRe = /(?:^|\n)(【[^】]*状态[^】]*】[\s\S]*)$/;
    const bracketMatch = text.match(bracketRe);
    if (bracketMatch) {
      const statusRaw = bracketMatch[1].trim();
      const matchStart = text.lastIndexOf(bracketMatch[1]);
      const cleanText = text.slice(0, matchStart).trim();
      return { cleanText, statusRaw };
    }

    // 格式④：**状态栏** / **状态信息** / **角色状态** 独立行开头
    const mdRe = /(?:^|\n)(\*{0,2}[^\n*]{0,10}状态栏\*{0,2})\s*\n([\s\S]*)$/;
    const mdMatch = text.match(mdRe);
    if (mdMatch) {
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
   *   ▷ 白邬内心安全感：28
   *   年龄：18岁 | 身高：165cm | 体重：42kg
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

    // 去掉 【状态栏】日期时间标题行
    text = text.replace(/^【[^】]*】[^\n]*\n?/m, '');

    // 按行解析
    const lines = text.split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;

      // 去掉 ▷ 符号前缀
      const noArrow = trimmed.replace(/^[▷►>→]\s*/, '');

      // 检查是否是单行多字段
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

      // 单字段行
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
      return;
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
    panel.classList.remove('d-none');
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
    if (body) { body.innerHTML = ''; body.classList.add('collapsed'); }
    const arrow = document.getElementById('csp-arrow');
    if (arrow) arrow.classList.add('collapsed');
    _collapsed = true;
  }

  return { stripStatusBlock, render, toggle, reset };
})();
