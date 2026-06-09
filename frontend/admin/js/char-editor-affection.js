/**
 * char-editor-affection.js - 好感度/沉浸度规则可视化编辑器
 *
 * 包含：好感度编辑器渲染、同步、校验、自定义事件增删、恢复默认、切换剧情类型刷新。
 * 依赖：utils.js (escHtml), config.js (AFFECTION_BASE_RULES 等), state.js (AdminState)
 * 被依赖：char-editor.js (renderEditPanel 调用 renderAffectionRuleEditor)
 */

// ============================================================
// 好感度可视化编辑器
// ============================================================
function renderAffectionRuleEditor(value) {
  let parsed = {};
  try {
    parsed = JSON.parse(value || '{}') || {};
  } catch (e) {
    parsed = {};
  }

  // 根据 card_type 和 scenario_type 选择事件组
  const cardType = (AdminState.currentCharData && AdminState.currentCharData.card_type) || 'intimate';
  const scenarioType = parsed.scenario_type || 'adventure'; // 从 affection_rules_json 读取

  const typeRuleMap = {
    intimate: {
      base: AFFECTION_BASE_RULES,
      all: AFFECTION_BASE_RULES,
      title: '❤️ 好感度规则可视化编辑器',
      desc: '不想直接写 JSON 的话，就在这里填。留空 = 使用系统默认值。',
      metricName: '好感度'
    },
    scenario_adventure: {
      base: ADVENTURE_AFFECTION_RULES,
      all: [...AFFECTION_BASE_RULES, ...ADVENTURE_AFFECTION_RULES],
      title: '🗡️ 冒险剧情沉浸度规则可视化编辑器',
      desc: '冒险剧情使用探索、战斗、解谜等事件。留空 = 使用系统默认值。',
      metricName: '沉浸度'
    },
    scenario_romance: {
      base: ROMANCE_AFFECTION_RULES,
      all: [...AFFECTION_BASE_RULES, ...ROMANCE_AFFECTION_RULES],
      title: '💕 恋爱剧情沉浸度规则可视化编辑器',
      desc: '恋爱剧情使用约会、告白、亲密互动等事件。留空 = 使用系统默认值。',
      metricName: '沉浸度'
    },
  };

  // 根据 card_type 和 scenario_type 选择配置
  let typeConfig;
  if (cardType === 'scenario') {
    typeConfig = scenarioType === 'romance' ? typeRuleMap.scenario_romance : typeRuleMap.scenario_adventure;
  } else {
    typeConfig = typeRuleMap.intimate;
  }

  const baseRules = typeConfig.base;
  const allRules = typeConfig.all;

  const positive = baseRules.filter(([, , score]) => score >= 0);
  const negative = baseRules.filter(([, , score]) => score < 0);
  const knownKeys = new Set(allRules.map(([key]) => key));
  const metaKeys = (typeof AdminCharEditorFields !== 'undefined' && AdminCharEditorFields.AFFECTION_META_KEYS)
    ? AdminCharEditorFields.AFFECTION_META_KEYS
    : new Set(['enabled', 'daily_cap', 'allow_regression', 'show_bar', 'scenario_type']);
  const customEntries = Object.entries(parsed).filter(([key]) => !metaKeys.has(key) && !knownKeys.has(key));

  const buildRows = (list) => list.map(([key, label, score]) => `
    <div class="affection-rule-row">
      <div class="affection-rule-name">${escHtml(label)}<span style="color:#666">（${escHtml(key)}，默认 ${score > 0 ? '+' : ''}${score}）</span></div>
      <input type="number" data-affection-key="${escHtml(key)}" value="${parsed[key] != null ? parsed[key] : ''}" placeholder="${score}" />
    </div>
  `).join('');

  const editorTitle = typeConfig.title;
  const editorDesc = typeConfig.desc;

  return `
    <div class="affection-editor">
      <div class="affection-editor-toolbar">
        <div>
          <div class="affection-editor-title">${editorTitle}</div>
          <div class="affection-editor-desc">${editorDesc}</div>
        </div>
        <label class="checkbox-group" style="margin-left:auto;">
          <input type="checkbox" id="affection-enabled-override" data-affection-sync="true" ${parsed.enabled === false ? '' : 'checked'} />
          <span>启用规则计算</span>
        </label>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button type="button" class="btn btn-ghost" data-action="reset-affection-rules">↺ 一键恢复默认</button>
        </div>
      </div>
      <div class="affection-grid">
        <div class="affection-card">
          <h4>正向事件</h4>
          ${buildRows(positive)}
        </div>
        <div class="affection-card">
          <h4>负向事件</h4>
          ${buildRows(negative)}
        </div>
      </div>
      <div class="affection-card" style="margin-top:10px;">
        <h4>自定义事件</h4>
        <div id="affection-custom-list" class="affection-custom-list" data-original-custom-keys="${escHtml(JSON.stringify(customEntries.map(([key]) => key)))}">
          ${customEntries.length ? customEntries.map(([key, score]) => `
            <div class="affection-custom-row">
              <input type="text" data-affection-custom-key value="${escHtml(key)}" placeholder="事件名，例如：study_together" />
              <input type="number" data-affection-custom-score value="${score}" placeholder="分值" />
              <button type="button" class="btn btn-ghost" data-action="remove-affection-custom-row">删除</button>
            </div>
          `).join('') : ''}
        </div>
        <div style="margin-top:10px;">
          <button type="button" class="btn btn-ghost" data-action="add-affection-custom-row">+ 新增自定义事件</button>
        </div>
      </div>
      <div class="affection-card" style="margin-top:10px;">
        <h4>⚙️ 高级配置</h4>
        <div class="affection-rule-row">
          <div class="affection-rule-name">每日${typeConfig.metricName}涨幅上限（daily_cap）<span style="color:#666">（默认 15，设为 0 = 不限制，适合剧情沙盒）</span></div>
          <input type="number" data-affection-meta="daily_cap" value="${parsed.daily_cap != null ? parsed.daily_cap : ''}" placeholder="15" min="0" max="100" />
        </div>
        <div class="affection-rule-row">
          <div class="affection-rule-name">允许阶段回退（allow_regression）<span style="color:#666">（默认关闭，开启后好感度下降会回退剧情阶段）</span></div>
          <select data-affection-meta="allow_regression">
            <option value="" ${parsed.allow_regression == null ? 'selected' : ''}>默认（关闭）</option>
            <option value="true" ${parsed.allow_regression === true ? 'selected' : ''}>✅ 开启</option>
            <option value="false" ${parsed.allow_regression === false ? 'selected' : ''}>🚫 关闭</option>
          </select>
        </div>
        <div class="affection-rule-row">
          <div class="affection-rule-name">隐藏聊天状态栏（show_bar）<span style="color:#666">（隐藏后用户看不到进度条、阶段、心情标签，增加探索未知感）</span></div>
          <select data-affection-meta="show_bar">
            <option value="" ${parsed.show_bar == null ? 'selected' : ''}>默认（显示）</option>
            <option value="true" ${parsed.show_bar === true ? 'selected' : ''}>👁 显示</option>
            <option value="false" ${parsed.show_bar === false ? 'selected' : ''}>🙈 隐藏</option>
          </select>
        </div>
      </div>
      <div class="affection-note">
        说明：<br />
        - 留空表示"沿用系统默认值"；<br />
        - “启用规则计算”关闭后才会停止该角色的${typeConfig.metricName}计算；<br />
        - daily_cap = 0 表示不限制每日涨幅，适合剧情沙盒让重度玩家一次性通关；<br />
        - 自定义事件名尽量用英文下划线，例如 study_together；<br />
        - 建议分值尽量控制在 -15 到 +15 之间。
      </div>
      <div id="affection-editor-status" class="affection-status">编辑器已就绪：留空就等于使用系统默认规则。</div>
    </div>
  `;
}

function addAffectionCustomRow(key = '', score = '') {
  const list = document.getElementById('affection-custom-list');
  if (!list) return;
  const row = document.createElement('div');
  row.className = 'affection-custom-row';
  row.innerHTML = `
    <input type="text" data-affection-custom-key value="${escHtml(key)}" placeholder="事件名，例如：study_together" />
    <input type="number" data-affection-custom-score value="${score}" placeholder="分值" />
    <button type="button" class="btn btn-ghost" data-action="remove-affection-custom-row">删除</button>
  `;
  list.appendChild(row);
  syncAffectionRulesEditor();
}

function removeAffectionCustomRow(btn) {
  btn.closest('.affection-custom-row')?.remove();
  syncAffectionRulesEditor();
}

function resetAffectionRulesEditor() {
  const enabledCheckbox = document.getElementById('affection-enabled-override');
  if (enabledCheckbox) enabledCheckbox.checked = true;

  document.querySelectorAll('[data-affection-key]').forEach(input => {
    input.value = '';
  });

  const list = document.getElementById('affection-custom-list');
  if (list) list.innerHTML = '';

  syncAffectionRulesEditor();
}

function validateAffectionRulesEditor() {
  const status = document.getElementById('affection-editor-status');
  if (!status) return;

  const issues = [];
  let filledCount = 0;
  const rawRules = document.getElementById('field-affection_rules_json');
  if (rawRules) {
    const jsonCheck = AdminCharEditorFields.validateAffectionRulesJson(rawRules.value);
    if (!jsonCheck.ok) issues.push(jsonCheck.message);
  }

  document.querySelectorAll('[data-affection-key]').forEach(input => {
    const key = input.getAttribute('data-affection-key');
    const raw = String(input.value || '').trim();
    if (!raw) return;
    filledCount += 1;
    const num = parseInt(raw, 10);
    if (Number.isNaN(num)) {
      issues.push(`${key} 不是有效数字`);
      return;
    }
    if (num > 15 || num < -15) {
      issues.push(`${key} 的分值 ${num} 超出推荐范围（-15 ~ +15）`);
    }
  });

  document.querySelectorAll('.affection-custom-row').forEach(row => {
    const key = row.querySelector('[data-affection-custom-key]')?.value?.trim() || '';
    const raw = row.querySelector('[data-affection-custom-score]')?.value?.trim() || '';
    if (!key && !raw) return;
    filledCount += 1;
    if (!/^[a-zA-Z0-9_]+$/.test(key)) {
      issues.push(`自定义事件名「${key || '（空）'}」建议只用英文、数字、下划线`);
    }
    const num = parseInt(raw, 10);
    if (raw && Number.isNaN(num)) {
      issues.push(`自定义事件「${key || '（空）'}」分值不是有效数字`);
      return;
    }
    if (raw && (num > 15 || num < -15)) {
      issues.push(`自定义事件「${key || '（空）'}」分值 ${num} 超出推荐范围（-15 ~ +15）`);
    }
  });

  if (issues.length) {
    status.className = 'affection-status warn';
    status.innerHTML = '⚠️ ' + issues.map(escHtml).join('<br />');
    return;
  }

  if (filledCount === 0) {
    status.className = 'affection-status ok';
    status.textContent = '✅ 当前没有自定义覆盖，保存后会使用系统默认好感度规则。';
    return;
  }

  status.className = 'affection-status ok';
  status.textContent = `✅ 当前已配置 ${filledCount} 项自定义好感度规则。`;
}

function syncAffectionRulesEditor() {
  const target = document.getElementById('field-affection_rules_json');
  if (!target) return;
  if (document.activeElement === target || target.dataset.affectionRawEdited === 'true') {
    validateAffectionRulesEditor();
    return;
  }
  let obj = {};
  try {
    const parsed = JSON.parse(target.value || '{}');
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      obj = parsed;
    }
  } catch (_) {
    const status = document.getElementById('affection-editor-status');
    if (status) {
      status.className = 'affection-status warn';
      status.textContent = '规则 JSON 不是合法 JSON，保存会被阻止。';
    }
    return;
  }
  const scenarioTypeField = document.getElementById('field-scenario_type');
  const scenarioType = scenarioTypeField ? scenarioTypeField.value : '';

  const enabledCheckbox = document.getElementById('affection-enabled-override');
  if (enabledCheckbox && !enabledCheckbox.checked) {
    obj.enabled = false;
  } else {
    delete obj.enabled;
  }
  if (scenarioType) {
    obj.scenario_type = scenarioType;
  } else {
    delete obj.scenario_type;
  }

  document.querySelectorAll('[data-affection-key]').forEach(input => {
    const key = input.getAttribute('data-affection-key');
    const raw = String(input.value || '').trim();
    if (!raw) {
      delete obj[key];
      return;
    }
    const num = parseInt(raw, 10);
    if (!Number.isNaN(num)) obj[key] = num;
  });

  const customList = document.getElementById('affection-custom-list');
  try {
    const originalCustomKeys = JSON.parse(customList?.dataset?.originalCustomKeys || '[]');
    originalCustomKeys.forEach(key => delete obj[key]);
  } catch (_) {
    // dataset 异常时忽略，下面仍会写入当前可见的自定义事件。
  }
  document.querySelectorAll('.affection-custom-row').forEach(row => {
    const key = row.querySelector('[data-affection-custom-key]')?.value?.trim();
    const raw = row.querySelector('[data-affection-custom-score]')?.value?.trim();
    if (!key || !raw) return;
    const num = parseInt(raw, 10);
    if (!Number.isNaN(num)) obj[key] = num;
  });

  // 高级配置项（daily_cap, allow_regression, scenario_type 等）
  document.querySelectorAll('[data-affection-meta]').forEach(el => {
    const metaKey = el.getAttribute('data-affection-meta');
    if (el.tagName === 'SELECT') {
      const val = el.value;
      if (val === 'true') obj[metaKey] = true;
      else if (val === 'false') obj[metaKey] = false;
      else if (val && val !== '') obj[metaKey] = val; // scenario_type 等字符串类型
      else delete obj[metaKey]; // 空值不写入，使用系统默认
    } else if (el.type === 'number') {
      const raw = String(el.value || '').trim();
      if (raw !== '') {
        const num = parseInt(raw, 10);
        if (!Number.isNaN(num)) obj[metaKey] = num;
      } else {
        delete obj[metaKey];
      }
    }
  });

  target.value = JSON.stringify(obj, null, 2);
  updateLen(target);
  validateAffectionRulesEditor();
}

function refreshAffectionEditor() {
  // 当 scenario_type 切换时，重新渲染好感度编辑器以显示对应的事件列表
  const affectionField = document.getElementById('field-affection_rules_json');
  if (!affectionField || !AdminState.currentCharData) return;

  const currentValue = affectionField.value;
  const affectionContainer = document.querySelector('.affection-editor');
  if (!affectionContainer) return;

  // 重新渲染编辑器
  affectionContainer.outerHTML = renderAffectionRuleEditor(currentValue);

  validateAffectionRulesEditor();
}
