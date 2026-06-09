/** 显示字段内联错误 */
function _showFieldError(fieldId, message) {
  const el = document.getElementById(fieldId);
  if (!el) { toast(message); return; }
  const group = el.closest('.form-group');
  if (group) {
    group.classList.add('has-error');
    const errDiv = document.createElement('div');
    errDiv.className = 'form-error-msg';
    errDiv.textContent = message;
    group.appendChild(errDiv);
  }
  el.focus();
  toast(message);
}

function openCreateCharModal() {
  // 清除所有之前的验证错误
  document.querySelectorAll('#create-char-modal .form-group.has-error').forEach(el => el.classList.remove('has-error'));
  document.querySelectorAll('#create-char-modal .form-error-msg').forEach(el => el.remove());
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
  document.getElementById('new-char-archetype').value = '';
  document.getElementById('new-char-required-plan').value = 'guest';
  document.getElementById('new-char-priority').value = '10';
  document.getElementById('new-char-visible').checked = true;
  document.getElementById('scenario-type-group').style.display = 'none';
  document.getElementById('archetype-group').style.display = '';
  document.getElementById('create-char-modal').style.display = 'flex';

  // 监听卡类型变化
  const typeSelect = document.getElementById('new-char-type');
  typeSelect.onchange = function() {
    const scenarioGroup = document.getElementById('scenario-type-group');
    scenarioGroup.style.display = this.value === 'scenario' ? '' : 'none';
    const archetypeGroup = document.getElementById('archetype-group');
    archetypeGroup.style.display = this.value === 'intimate' ? '' : 'none';
  };
}

function closeCreateCharModal() {
  document.getElementById('create-char-modal').style.display = 'none';
}

async function createCharacter() {
  // 清除所有之前的验证错误
  document.querySelectorAll('#create-char-modal .form-group.has-error').forEach(el => el.classList.remove('has-error'));
  document.querySelectorAll('#create-char-modal .form-error-msg').forEach(el => el.remove());

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
  const archetype = document.getElementById('new-char-archetype').value;
  const cardType = document.getElementById('new-char-type').value;
  const requiredPlan = document.getElementById('new-char-required-plan').value;
  const priority = parseInt(document.getElementById('new-char-priority').value) || 10;
  const isVisible = document.getElementById('new-char-visible').checked ? 1 : 0;

  if (!id) {
    _showFieldError('new-char-id', '请输入角色ID');
    return;
  }
  if (!name) {
    _showFieldError('new-char-name', '请输入角色名');
    return;
  }
  if (!systemPrompt) {
    _showFieldError('new-char-system-prompt', '请输入主指令（System Prompt）');
    return;
  }
  if (!/^[a-zA-Z0-9_]+$/.test(id)) {
    _showFieldError('new-char-id', '角色ID只能包含英文、数字和下划线');
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
    // 原型存在时立即写入 runtime_cache_json
    if (archetype) {
      await AdminAPI.apiFetch(`${AdminAPI.API}/character/${id}`, {
        method: 'POST',
        body: JSON.stringify({ updates: { rl__archetype: archetype } }),
      });
    }
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

  // 防止重复提交
  if (AdminState.isSaving) {
    toast('正在保存中，请稍等…');
    return;
  }
  AdminState.isSaving = true;

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
    AdminState.isSaving = false;
    toast(`❌ 还有 ${missing.length} 个必填项未填写：${missing.join('、')}`);
    return;
  }

  syncAffectionRulesEditor();
  syncLifeProfileEditor();
  syncPhaseBehaviorsEditor();

  const riskWarnings = AdminCharEditorFields.getRiskWarnings({
    cardType: document.getElementById('field-card_type')?.value || AdminState.currentCharData?.card_type || 'intimate',
    lifeProfileJson: document.getElementById('field-life_profile_json')?.value || AdminState.currentCharData?.life_profile_json || '{}',
    systemPrompt: document.getElementById('field-system_prompt')?.value || '',
    primarySystemPrompt: document.getElementById('field-rl__primary_system_prompt')?.value || AdminState.currentCharData?.rl__primary_system_prompt || '',
    openingMessage: document.getElementById('field-opening_message')?.value || '',
    affectionEnabled: document.getElementById('field-affection_enabled')?.value ?? AdminState.currentCharData?.affection_enabled,
    affectionRulesJson: document.getElementById('field-affection_rules_json')?.value || AdminState.currentCharData?.affection_rules_json || '{}',
  });
  if (riskWarnings.length > 0) {
    const confirmed = await showConfirm(`检测到 ${riskWarnings.length} 个配置提醒：\n\n${riskWarnings.join('\n')}\n\n仍然保存？`, '保存提醒');
    if (!confirmed) {
      AdminState.isSaving = false;
      return;
    }
  }

  const updates = {};

  try {
    for (const field of AdminCharEditorFields.listAllFixedFields()) {
      const el = document.getElementById(`field-${field}`);
      if (!el) continue;
      if (field === 'tags') {
        updates.tags = formTagsToServer(el.value);
        continue;
      }
      if (field === 'affection_rules_json') {
        syncAffectionRulesEditor();
        const jsonCheck = AdminCharEditorFields.validateAffectionRulesJson(el.value);
        if (!jsonCheck.ok) throw new Error(jsonCheck.message);
        updates[field] = el.value.trim() || '{}';
        continue;
      }
      if (field === 'life_profile_json') {
        syncLifeProfileEditor();
        updates[field] = validateJsonString(el.value, '人生档案');
        continue;
      }
      if (field === 'phase_behaviors_json') {
        syncPhaseBehaviorsEditor();
        updates[field] = validateJsonString(el.value, '阶段行为');
        continue;
      }
      let val = el.value;
      if (FIXED_FIELD_META[field]?.type === 'number') val = parseInt(val, 10) || 0;
      if (['is_visible', 'import_locked', 'affection_enabled'].includes(field)) val = parseInt(val, 10);
      updates[field] = val;
    }

    const scenarioTypeEl = document.getElementById('field-scenario_type');
    if (scenarioTypeEl && !Object.prototype.hasOwnProperty.call(updates, 'affection_rules_json')) {
      const mergedRules = AdminCharEditorFields.upsertAffectionMeta(
        AdminState.currentCharData?.affection_rules_json || '{}',
        'scenario_type',
        scenarioTypeEl.value
      );
      updates.affection_rules_json = JSON.stringify(mergedRules, null, 2);
    }

    for (const rlKey of AdminState.currentRlFields) {
      const el = document.getElementById(`field-rl__${rlKey}`);
      if (!el) continue;
      const jsonCheck = AdminCharEditorFields.validateDangerousRuntimeJson(rlKey, el.value);
      if (!jsonCheck.ok) throw new Error(jsonCheck.message);
      updates[`rl__${rlKey}`] = el.value;
    }
  } catch (e) {
    AdminState.isSaving = false;
    toast(e.message || String(e));
    return;
  }

  const statusEl = document.getElementById('save-status');
  const fabLabel = document.getElementById('fab-label');
  if (statusEl) { statusEl.textContent = '保存中...'; statusEl.className = 'save-status'; }
  if (fabLabel) { fabLabel.textContent = '保存中…'; fabLabel.className = 'fab-label is-saving'; }

  try {
    await AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}`, {
      method: 'POST',
      body: JSON.stringify({ updates }),
    });
    const refreshed = await AdminAPI.apiFetch(`${AdminAPI.API}/character/${AdminState.currentCharId}`);
    AdminState.currentCharData = normalizeCharacterDetail(refreshed);
    AdminState.isDirty = false;
    AdminState.isSaving = false;
    if (statusEl) { statusEl.textContent = '✅ 保存成功！'; statusEl.className = 'save-status ok'; }
    const dirtyEl = document.getElementById('dirty-indicator');
    if (dirtyEl) dirtyEl.classList.add('d-none');
    if (fabLabel) { fabLabel.textContent = '✅ 已保存'; fabLabel.className = 'fab-label is-success'; setTimeout(()=>{ fabLabel.textContent='保存'; fabLabel.className='fab-label'; }, 2500); }
    toast('保存成功！修改立即生效（无需重启）');
    loadCharList();
    loadCharacterSummary();
    loadPromptPreview();
  } catch (e) {
    AdminState.isSaving = false;
    if (statusEl) { statusEl.textContent = `❌ 保存失败：${e.message}`; statusEl.className = 'save-status err'; }
    if (fabLabel) { fabLabel.textContent = '❌ 失败'; fabLabel.className = 'fab-label is-error'; setTimeout(()=>{ fabLabel.textContent='保存'; fabLabel.className='fab-label'; }, 3000); }
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
