function renderCharacterOverview(summary) {
  const container = document.getElementById('tab-overview');
  if (!summary) {
    container.innerHTML = '<div class="empty-state"><div class="icon">👈</div><div>从左侧选择一个角色开始</div></div>';
    return;
  }

  const stats = summary.stats || {};
  const warnings = Array.from(new Set([...(summary.warnings || []), ...buildExtraWarnings(summary)]));
  const completeness = summary.completeness ?? 0;
  const scoreClass = completeness >= 80 ? 'ok' : 'warn';
  const checklist = buildChecklist(summary);
  const nextActions = checklist.filter(x => !x.ok).slice(0, 3);
  const activeMemories = stats.active_memories ?? stats.memories ?? 0;
  const activeGreetings = stats.active_greetings ?? stats.greetings ?? 0;
  const activeStorylines = stats.active_storylines ?? stats.storylines ?? 0;
  const activeEvents = stats.active_events ?? stats.events ?? 0;

  container.innerHTML = `
    <div class="overview-card">
      <div class="overview-title">📊 角色总览</div>
      <div class="overview-hero">
        <div>
          <div class="overview-name">${escHtml(summary.name || AdminState.currentCharData?.name || AdminState.currentCharId || '')}</div>
          <div class="overview-subtitle">${escHtml(summary.subtitle || AdminState.currentCharData?.subtitle || '补齐基础说明、开场白、剧情线与记忆后，这个角色会更易运营。')}</div>
        </div>
        <div class="overview-score">
          <div class="score-value">${completeness}</div>
          <div class="score-label">配置完整度</div>
        </div>
      </div>
      <div class="overview-meta">
        <div class="overview-stat">
          <div class="stat-label">记忆条目</div>
          <div class="stat-value">${activeMemories}</div>
          <div class="stat-sub">启用中 / 总数 ${stats.memories || 0}</div>
        </div>
        <div class="overview-stat">
          <div class="stat-label">开场白</div>
          <div class="stat-value">${activeGreetings}</div>
          <div class="stat-sub">覆盖 ${stats.greeting_phase_coverage || 0} 个阶段</div>
        </div>
        <div class="overview-stat">
          <div class="stat-label">剧情线</div>
          <div class="stat-value">${activeStorylines}</div>
          <div class="stat-sub">默认剧情线 ${summary.default_storyline_id ? '已设置' : '未设置'}</div>
        </div>
        <div class="overview-stat">
          <div class="stat-label">剧情事件</div>
          <div class="stat-value">${activeEvents}</div>
          <div class="stat-sub">缺解锁 ${stats.empty_unlock_events || 0} / 缺文案 ${stats.empty_event_content_events || 0}</div>
        </div>
      </div>
    </div>
    <div class="health-card">
      <div class="health-title">🩺 配置健康检查</div>
      <div class="health-list">
        ${warnings.length ? warnings.map(item => `<div class="health-item ${scoreClass}">⚠️ ${escHtml(item)}</div>`).join('') : '<div class="health-item ok">✅ 目前没有明显配置缺口，可以继续做精细化优化。</div>'}
      </div>
      <div class="diagnostic-grid">
        ${checklist.map(item => `
          <div class="diagnostic-item ${item.ok ? 'ok' : 'warn'}">
            <div class="title">${item.ok ? '✅ ' : '⚠️ '}${escHtml(item.title)}</div>
            <div>${escHtml(item.text)}</div>
          </div>
        `).join('')}
      </div>
      <div class="quick-actions">
        ${nextActions.length ? nextActions.map(item => `<span class="item-badge">下一步：${escHtml(item.title)}</span>`).join('') : '<span class="item-badge active">当前这张卡已经比较完整了</span>'}
      </div>
    </div>
  `;
}

async function loadCharacterSummary() {
  if (!AdminState.currentCharId) return;
  try {
    const summary = await AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}/config-summary`);
    AdminState.currentCharSummary = summary;
    renderCharacterOverview(summary);
  } catch (e) {
    AdminState.currentCharSummary = null;
    document.getElementById('tab-overview').innerHTML = `
      <div class="health-card" style="grid-column:1/-1">
        <div class="health-title">🩺 配置健康检查</div>
        <div class="health-item warn">加载角色总览失败：${escHtml(e.message)}</div>
      </div>
    `;
  }
}

function parseAffectionRules(raw) {
  const text = String(raw || '').trim();
  if (!text) return null;
  try { return JSON.parse(text); } catch (e) { return null; }
}

function getMetricName() {
  const ct = AdminState.currentCharData?.card_type || 'intimate';
  const map = { intimate: '好感度', scenario: '沉浸度' };
  return map[ct] || '好感度';
}

function hasUsableAffectionRules(raw) {
  const parsed = parseAffectionRules(raw);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') return false;
  return Object.values(parsed).some(value => {
    if (value == null) return false;
    if (Array.isArray(value)) return value.length > 0;
    if (typeof value === 'object') return Object.keys(value).length > 0;
    if (typeof value === 'string') return value.trim() !== '';
    return true;
  });
}

function buildExtraWarnings(summary) {
  const extra = [];
  const stats = summary?.stats || {};
  const storylines = AdminState.advancedData.storylines || [];
  const greetings = AdminState.advancedData.greetings || [];
  const phases = new Set(greetings.filter(x => x.is_active).map(x => x.story_phase));
  const activeMemories = stats.active_memories ?? stats.memories ?? 0;
  const activeGreetings = stats.active_greetings ?? stats.greetings ?? 0;
  const activePostRules = stats.active_post_rules ?? stats.post_rules ?? 0;
  const phaseCoverage = stats.greeting_phase_coverage ?? phases.size;
  const affectionVisible = AdminState.currentCharData?.affection_enabled === 1 || AdminState.currentCharData?.affection_enabled === '1';
  const hasAffectionRules = hasUsableAffectionRules(AdminState.currentCharData?.affection_rules_json);

  if (affectionVisible && !hasAffectionRules) {
    extra.push(`已启用${getMetricName()}系统，但${getMetricName()}规则还是空的。`);
  }
  if (activeMemories > 0 && activeMemories < 3) {
    extra.push('当前启用中的记忆条目偏少，建议至少保留 3 条高频记忆。');
  }
  if (activeGreetings > 0 && phaseCoverage > 0 && phaseCoverage < 2) {
    extra.push('开场白阶段比较单一，建议至少覆盖 2 个关系阶段。');
  }
  if ((stats.post_rules || 0) > 0 && activePostRules === 0) {
    extra.push('后置规则虽然配置了，但目前全部处于禁用状态。');
  }
  if (storylines.length > 0 && !summary.default_storyline_id) {
    extra.push('已有剧情线，但还没有设置默认剧情线。');
  }
  if ((stats.events || 0) > 0 && (stats.storylines || 0) === 0) {
    extra.push('已经配置剧情事件，但没有剧情线，后续扩展会不方便。');
  }
  if ((stats.empty_unlock_events || 0) > 0) {
    extra.push(`有 ${stats.empty_unlock_events} 个剧情事件还没有配置任何解锁内容。`);
  }
  if ((stats.empty_event_content_events || 0) > 0) {
    extra.push(`有 ${stats.empty_event_content_events} 个剧情事件还没有触发文案，剧情衔接可能生硬。`);
  }
  return extra;
}

function buildChecklist(summary) {
  const stats = summary?.stats || {};
  const greetings = AdminState.advancedData.greetings || [];
  const storylines = AdminState.advancedData.storylines || [];
  const memories = AdminState.advancedData.memories || [];
  const events = AdminState.advancedData.events || [];
  const phases = new Set(greetings.filter(x => x.is_active).map(x => x.story_phase));
  const activeMemories = stats.active_memories ?? memories.filter(x => x.is_active).length;
  const activeGreetings = stats.active_greetings ?? greetings.filter(x => x.is_active).length;
  const activeStorylines = stats.active_storylines ?? storylines.filter(x => x.is_active).length;
  const activePostRules = stats.active_post_rules ?? (AdminState.advancedData.postRules || []).filter(x => x.is_active).length;
  const activeEvents = stats.active_events ?? events.filter(x => x.is_active).length;
  const phaseCoverage = stats.greeting_phase_coverage ?? phases.size;
  const emptyUnlockEvents = stats.empty_unlock_events ?? events.filter(e => !(splitCsvIds(e.unlocked_memory_ids).length || splitCsvIds(e.unlocked_greeting_ids).length || e.unlocked_storyline_id)).length;
  const emptyEventContentEvents = stats.empty_event_content_events ?? events.filter(e => !String(e.event_content || '').trim()).length;
  const affectionVisible = AdminState.currentCharData?.affection_enabled === 1 || AdminState.currentCharData?.affection_enabled === '1';
  const hasAffectionRules = hasUsableAffectionRules(AdminState.currentCharData?.affection_rules_json);

  return [
    {
      ok: Boolean((AdminState.currentCharData?.name || '').trim() && (AdminState.currentCharData?.system_prompt || '').trim()),
      title: '基础资料',
      text: (AdminState.currentCharData?.name || '').trim() && (AdminState.currentCharData?.system_prompt || '').trim()
        ? '角色名和主指令都已填写。'
        : '建议先补齐角色名和主指令，这是最基础的两项。'
    },
    {
      ok: activeMemories >= 3,
      title: '记忆条目',
      text: activeMemories >= 3
        ? `当前已有 ${activeMemories} 条启用中的记忆，基础注入够用了。`
        : `当前只有 ${activeMemories || 0} 条启用中的记忆（总数 ${stats.memories || 0}），建议至少准备 3 条常用触发内容。`
    },
    {
      ok: phaseCoverage >= 2,
      title: '开场白阶段覆盖',
      text: phaseCoverage >= 2
            ? `已覆盖 ${phaseCoverage} 个关系阶段。`
            : `当前只有 ${activeGreetings || 0} 条启用中的开场白，建议至少覆盖前两个阶段。`
    },
    {
      ok: activeStorylines === 0 || Boolean(summary.default_storyline_id),
      title: '默认剧情线',
      text: activeStorylines === 0
        ? '目前还没配剧情线，可以暂时先不配。'
        : (summary.default_storyline_id ? '已设置默认剧情线。' : '已有剧情线，但还没指定默认剧情线。')
    },
    {
      ok: activeEvents === 0 || (emptyUnlockEvents === 0 && emptyEventContentEvents === 0),
      title: '剧情事件完整度',
      text: activeEvents === 0
        ? '还没有剧情事件，后续可以按好感阈值逐步添加。'
        : ((emptyUnlockEvents === 0 && emptyEventContentEvents === 0)
            ? '所有启用中的剧情事件都具备解锁内容和触发文案。'
            : `当前还有 ${emptyUnlockEvents} 个事件缺解锁内容、${emptyEventContentEvents} 个事件缺触发文案。`)
    },
    {
      ok: (stats.post_rules || 0) === 0 || activePostRules > 0,
      title: '后置规则可用性',
      text: (stats.post_rules || 0) === 0
        ? '目前还没有配置后置规则。'
        : (activePostRules > 0
            ? `已有 ${activePostRules} 条启用中的后置规则。`
            : '虽然后置规则已配置，但现在全部是禁用状态。')
    },
    {
      ok: !affectionVisible || hasAffectionRules,
      title: getMetricName() + '状态栏',
      text: !affectionVisible
        ? '当前角色隐藏了' + getMetricName() + '状态栏。后台仍会计算好感度。'
        : (hasAffectionRules
            ? getMetricName() + '状态栏已显示，且已有有效规则配置。'
            : getMetricName() + '状态栏已显示，但规则还是空的。系统会使用默认规则。')
    }
  ];
}
