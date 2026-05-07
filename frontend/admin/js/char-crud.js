function openCreateCharModal() {
  document.getElementById('new-char-id').value = '';
  document.getElementById('new-char-name').value = '';
  document.getElementById('new-char-abbr').value = '';
  document.getElementById('new-char-subtitle').value = '';
  document.getElementById('new-char-description').value = '';
  document.getElementById('new-char-avatar-url').value = '';
  document.getElementById('new-char-cover-url').value = '';
  document.getElementById('new-char-system-prompt').value = '';
  document.getElementById('new-char-opening').value = '';
  document.getElementById('new-char-tags').value = '';
  document.getElementById('new-char-type').value = 'intimate';
  document.getElementById('new-char-scenario-type').value = 'adventure';
  document.getElementById('new-char-required-plan').value = 'guest';
  document.getElementById('new-char-priority').value = '10';
  document.getElementById('new-char-visible').checked = true;
  document.getElementById('scenario-type-group').style.display = 'none';
  document.getElementById('create-char-modal').style.display = 'flex';

  // 监听卡类型变化
  const typeSelect = document.getElementById('new-char-type');
  typeSelect.onchange = function() {
    const scenarioGroup = document.getElementById('scenario-type-group');
    scenarioGroup.style.display = this.value === 'scenario' ? '' : 'none';
  };
}

function closeCreateCharModal() {
  document.getElementById('create-char-modal').style.display = 'none';
}

async function createCharacter() {
  const id = document.getElementById('new-char-id').value.trim();
  const name = document.getElementById('new-char-name').value.trim();
  const abbr = document.getElementById('new-char-abbr').value.trim();
  const subtitle = document.getElementById('new-char-subtitle').value.trim();
  const description = document.getElementById('new-char-description').value.trim();
  const avatarUrl = document.getElementById('new-char-avatar-url').value.trim();
  const coverUrl = document.getElementById('new-char-cover-url').value.trim();
  const systemPrompt = document.getElementById('new-char-system-prompt').value.trim();
  const opening = document.getElementById('new-char-opening').value.trim();
  const tagsStr = document.getElementById('new-char-tags').value.trim();
  const cardType = document.getElementById('new-char-type').value;
  const requiredPlan = document.getElementById('new-char-required-plan').value;
  const priority = parseInt(document.getElementById('new-char-priority').value) || 10;
  const isVisible = document.getElementById('new-char-visible').checked ? 1 : 0;

  if (!id) {
    toast('请输入角色ID');
    return;
  }
  if (!name) {
    toast('请输入角色名');
    return;
  }
  if (!systemPrompt) {
    toast('请输入主指令（System Prompt）');
    return;
  }
  if (!/^[a-zA-Z0-9_]+$/.test(id)) {
    toast('角色ID只能包含英文、数字和下划线');
    return;
  }

  const tags = tagsStr ? JSON.stringify(tagsStr.split(',').map(t => t.trim()).filter(t => t)) : '[]';

  // 构建 affection_rules_json（包含 scenario_type）
  const affectionRules = {};
  if (cardType === 'scenario') {
    const scenarioType = document.getElementById('new-char-scenario-type').value;
    affectionRules.scenario_type = scenarioType;
  }

  const data = {
    id,
    name,
    abbr: abbr || name,
    subtitle,
    description,
    avatar_url: avatarUrl,
    cover_url: coverUrl,
    system_prompt: systemPrompt,
    opening_message: opening,
    tags,
    card_type: cardType,
    required_plan: requiredPlan,
    home_priority: priority,
    is_visible: isVisible,
    affection_rules_json: JSON.stringify(affectionRules),
  };

  try {
    await AdminAPI.apiFetch(`${AdminAPI.API}/characters`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
    closeCreateCharModal();
    toast('✅ 角色创建成功！');
    await loadCharList();
    await selectChar(id);
  } catch (e) {
    toast('创建失败：' + e.message);
  }
}

async function saveChar() {
  if (!AdminState.currentCharId) {
    toast('请先在左侧选择一个角色再保存');
    return;
  }

  // 必填项校验
  const requiredFields = [
    { id: 'field-name', label: '角色名' },
    { id: 'field-subtitle', label: '简介（副标题）' },
    { id: 'field-opening_message', label: '开场白' },
    { id: 'field-system_prompt', label: '主指令' },
  ];
  const missing = [];
  for (const {id, label} of requiredFields) {
    const el = document.getElementById(id);
    if (el && !el.value.trim()) {
      missing.push(label);
      el.style.borderColor = '#dc2626';
    } else if (el) {
      el.style.borderColor = '';
    }
  }
  if (missing.length > 0) {
    toast(`❌ 还有 ${missing.length} 个必填项未填写：${missing.join('、')}`);
    return;
  }

  const updates = {};

  try {
    for (const section of FIXED_SECTIONS) {
      for (const field of section.fields) {
        const el = document.getElementById(`field-${field}`);
        if (!el) continue;
        if (field === 'tags') {
          updates.tags = formTagsToServer(el.value);
          continue;
        }
        if (field === 'affection_rules_json') {
          syncAffectionRulesEditor();
          updates[field] = validateJsonString(el.value, '好感度规则');
          continue;
        }
        if (field === 'life_profile_json') {
          syncLifeProfileEditor();
          updates[field] = validateJsonString(el.value, '人生档案');
          continue;
        }
        let val = el.value;
        if (FIXED_FIELD_META[field]?.type === 'number') val = parseInt(val, 10) || 0;
        if (['is_visible', 'import_locked', 'affection_enabled'].includes(field)) val = parseInt(val, 10);
        updates[field] = val;
      }
    }

    for (const rlKey of AdminState.currentRlFields) {
      const el = document.getElementById(`field-rl__${rlKey}`);
      if (!el) continue;
      updates[`rl__${rlKey}`] = el.value;
    }
  } catch (e) {
    toast(e.message || String(e));
    return;
  }

  const statusEl = document.getElementById('save-status');
  const fabLabel = document.getElementById('fab-label');
  if (statusEl) { statusEl.textContent = '保存中...'; statusEl.className = 'save-status'; }
  if (fabLabel) { fabLabel.textContent = '保存中…'; fabLabel.style.color = '#888'; }

  try {
    await AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}`, {
      method: 'POST',
      body: JSON.stringify({ updates }),
    });
    const refreshed = await AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}`);
    AdminState.currentCharData = normalizeCharacterDetail(refreshed);
    if (statusEl) { statusEl.textContent = '✅ 保存成功！'; statusEl.className = 'save-status ok'; }
    if (fabLabel) { fabLabel.textContent = '✅ 已保存'; fabLabel.style.color = '#4ade80'; setTimeout(()=>{ fabLabel.textContent='保存'; fabLabel.style.color='#c084fc'; }, 2500); }
    toast('保存成功！修改立即生效（无需重启）');
    loadCharList();
    loadCharacterSummary();
    loadPromptPreview();
  } catch (e) {
    if (statusEl) { statusEl.textContent = `❌ 保存失败：${e.message}`; statusEl.className = 'save-status err'; }
    if (fabLabel) { fabLabel.textContent = '❌ 失败'; fabLabel.style.color = '#f87171'; setTimeout(()=>{ fabLabel.textContent='保存'; fabLabel.style.color='#c084fc'; }, 3000); }
    toast('保存失败：' + e.message);
  }
}

async function deleteCurrentCharacter() {
  if (!AdminState.currentCharId) return;

  const characterId = AdminState.currentCharId;
  const characterName = AdminState.currentCharData?.name || characterId;
  const confirmMsg =
    `确定要删除角色「${characterName}」吗？\n\n` +
    `会同时删除该角色的记忆、开场白、剧情线、剧情事件以及关联聊天记录，此操作不可撤销。`;
  const confirmed = await showConfirm(confirmMsg, '删除角色');
  if (!confirmed) return;

  try {
    await AdminAPI.apiFetch(`${AdminAPI.API}/character/${characterId}`, { method: 'DELETE' });
    clearCurrentCharacterSelection();
    await loadCharList();
    toast(`已删除角色：${characterName}`);
  } catch (e) {
    toast('删除失败：' + e.message);
  }
}

function toggleBeginnerMode() {
  const current = localStorage.getItem('admin_beginner_mode') !== 'false';
  localStorage.setItem('admin_beginner_mode', current ? 'false' : 'true');
  if (AdminState.currentCharData) {
    renderEditPanel(AdminState.currentCharData);
  }
}

function hideGuide() {
  localStorage.setItem('admin_hide_guide', 'true');
  if (AdminState.currentCharData) {
    renderEditPanel(AdminState.currentCharData);
  }
}
