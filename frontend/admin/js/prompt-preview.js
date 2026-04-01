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

async function loadPromptPreview() {
  const container = document.getElementById('prompt-preview-content');
  if (!AdminState.currentCharId) {
    container.innerHTML = '<div class="preview-box muted">请先从左侧选择角色。</div>';
    return;
  }
  container.innerHTML = '<div class="preview-box muted">正在生成 Prompt 预览...</div>';
  try {
    const data = await AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}/message-preview`);
    AdminState.currentPromptPreview = data;
    const messages = Array.isArray(data.messages) ? data.messages : [];
    const systemParts = messages
      .filter(m => String(m.role || '').toLowerCase() === 'system')
      .map(m => m.content || '')
      .filter(Boolean);
    const latestUser = [...messages].reverse().find(m => String(m.role || '').toLowerCase() === 'user');
    const sourceSections = buildPromptSourceSections();

    container.innerHTML = `
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
