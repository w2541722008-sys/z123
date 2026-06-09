/**
 * prompt-preview.js - Prompt 预览标签页逻辑
 *
 * 包含：预览加载、复制、来源拆解。
 * 依赖：utils.js, api.js, state.js
 */

function buildPromptSourceSections() {
  const sections = [];
  if (AdminState.currentCharData?.system_prompt) {
    sections.push({ title: '固定主指令', content: AdminState.currentCharData.system_prompt });
  }
  const rl = AdminState.currentCharData?.runtime_layers || {};
  if (rl.base_profile) sections.push({ title: '角色档案 / base_profile', content: rl.base_profile });
  if (rl.scenario) sections.push({ title: '场景设定 / scenario', content: rl.scenario });
  if (rl.world_rules) sections.push({ title: '世界规则 / world_rules', content: rl.world_rules });
  if ((AdminState.advancedData.memories || []).some(x => x.is_active)) {
    sections.push({
      title: '可触发记忆条目',
      content: (AdminState.advancedData.memories || []).filter(x => x.is_active).slice(0, 5).map(x => `- ${x.keywords}`).join('\n')
    });
  }
  if ((AdminState.advancedData.postRules || []).some(x => x.is_active)) {
    sections.push({
      title: '后置规则',
      content: (AdminState.advancedData.postRules || []).filter(x => x.is_active).slice(0, 5).map(x => `- ${x.name}`).join('\n')
    });
  }
  return sections.filter(x => x.content);
}

function getPromptPreviewQuery() {
  const params = new URLSearchParams();
  const sample = document.getElementById('prompt-preview-sample')?.value || '';
  const affection = document.getElementById('prompt-preview-affection')?.value || '';
  const phase = document.getElementById('prompt-preview-phase')?.value || '';
  const mood = document.getElementById('prompt-preview-mood')?.value || '';
  const storyline = document.getElementById('prompt-preview-storyline')?.value || '';
  const customVars = document.getElementById('prompt-preview-custom-vars')?.value || '';
  if (sample.trim()) params.set('sample_user_message', sample.trim());
  if (affection !== '') params.set('affection', String(Math.max(0, Math.min(100, parseInt(affection, 10) || 0))));
  if (phase) params.set('story_phase', phase);
  if (mood) params.set('mood', mood);
  if (storyline.trim()) params.set('storyline_id', storyline.trim());
  if (customVars.trim()) {
    try {
      const parsed = JSON.parse(customVars);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
        throw new Error('custom_vars must be object');
      }
      params.set('custom_vars_json', JSON.stringify(parsed));
    } catch (e) {
      return { error: '自定义变量 JSON 格式错误，请输入对象，例如 {"has_key":true}' };
    }
  }
  const query = params.toString();
  return { query: query ? `?${query}` : '' };
}

function buildPreviewSummaryHtml(summary = {}) {
  const items = [
    ['模拟消息', summary.has_sample_user_message],
    ['世界书/记忆', summary.has_world_info],
    ['后置规则', summary.has_post_rules],
    ['状态快照', summary.has_state_snapshot],
  ];
  return `<div class="preview-section">
    <h4>命中摘要</h4>
    <div class="preview-summary-grid">
      ${items.map(([label, hit]) => `<div class="preview-summary-item ${hit ? 'hit' : ''}">${hit ? '✓' : '—'} ${escHtml(label)}</div>`).join('')}
    </div>
  </div>`;
}

async function loadPromptPreview() {
  const container = document.getElementById('prompt-preview-content');
  if (!AdminState.currentCharId) {
    container.innerHTML = '<div class="preview-box muted">请先从左侧选择角色。</div>';
    return;
  }
  container.innerHTML = '<div class="preview-box muted">正在生成 Prompt 预览...</div>';
  try {
    const queryResult = getPromptPreviewQuery();
    if (queryResult.error) {
      AdminState.currentPromptPreview = null;
      container.innerHTML = `<div class="preview-box muted">${escHtml(queryResult.error)}</div>`;
      return;
    }
    const query = queryResult.query || '';
    const data = await AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}/message-preview${query}`);
    AdminState.currentPromptPreview = data;
    const messages = Array.isArray(data.messages) ? data.messages : [];
    const systemParts = messages
      .filter(m => String(m.role || '').toLowerCase() === 'system')
      .map(m => m.content || '')
      .filter(Boolean);
    const latestUser = [...messages].reverse().find(m => String(m.role || '').toLowerCase() === 'user');
    const sourceSections = buildPromptSourceSections();

    container.innerHTML = `
      ${buildPreviewSummaryHtml(data.preview_summary)}
      <div class="preview-section">
        <h4>System Prompt 拼装结果</h4>
        <div class="preview-box">${escHtml(systemParts.join('\n\n---\n\n') || '（无 system 内容）')}</div>
      </div>
      <div class="preview-section">
        <h4>你当前这份 Prompt 主要来自哪里</h4>
        <div class="preview-source-list">
          ${sourceSections.length ? sourceSections.map(section => `
            <div class="preview-source-item">
              <div class="source-title">${escHtml(section.title)}</div>
              <div class="source-content">${escHtml(String(section.content).slice(0, 500))}</div>
            </div>
          `).join('') : '<div class="preview-box muted">暂时没有可拆解的来源信息。</div>'}
        </div>
      </div>
      <div class="preview-section">
        <h4>最新用户消息</h4>
        <div class="preview-box ${latestUser?.content ? '' : 'muted'}">${escHtml(latestUser?.content || '暂无用户消息，当前为纯预览模式。')}</div>
      </div>
    `;
  } catch (e) {
    AdminState.currentPromptPreview = null;
    container.innerHTML = `<div class="preview-box muted">生成失败：${escHtml(e.message)}</div>`;
  }
}

async function copyPromptPreview() {
  const payload = AdminState.currentPromptPreview;
  if (!payload) {
    toast('还没有可复制的 Prompt 预览');
    return;
  }
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  const text = messages.map(m => `[${String(m.role || '').toUpperCase()}]\n${m.content || ''}`).join('\n\n');
  try {
    await navigator.clipboard.writeText(text);
    toast('Prompt 预览已复制');
  } catch (e) {
    toast('复制失败：' + e.message);
  }
}
