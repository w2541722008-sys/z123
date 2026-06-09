/**
 * 管理后台角色编辑字段配置测试。
 *
 * 运行方式：node tests/frontend/test_admin_char_editor_fields.js
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const projectRoot = path.resolve(__dirname, '..', '..');
const fieldsPath = path.join(projectRoot, 'frontend', 'admin', 'js', 'char-editor-fields.js');
const source = fs.readFileSync(fieldsPath, 'utf8');

const sandbox = { console };
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: fieldsPath });

const fields = sandbox.AdminCharEditorFields;

function sameArray(actual, expected) {
  assert.deepStrictEqual(Array.from(actual), expected);
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

(function runTests() {
  assert.ok(fields, 'AdminCharEditorFields should be exported');

  const beginnerIntimate = fields.resolveEditorLayout({
    cardType: 'intimate',
    isBeginnerMode: true,
    availableRlKeys: ['base_profile', 'examples', 'personality', 'world_rules'],
  });
  sameArray(
    beginnerIntimate.sections.map(section => section.id),
    ['listing', 'aiCore', 'playConfig']
  );
  sameArray(
    beginnerIntimate.sections.flatMap(section => section.fixedFields || []),
    ['name', 'subtitle', 'opening_message', 'avatar_url', 'cover_url', 'is_visible', 'home_priority', 'system_prompt', 'card_type']
  );
  sameArray(
    beginnerIntimate.sections.flatMap(section => section.rlFields || []),
    ['base_profile', 'examples']
  );

  const fullScenario = fields.resolveEditorLayout({
    cardType: 'scenario',
    isBeginnerMode: false,
    availableRlKeys: [
      'base_profile',
      'examples',
      'scenario',
      'world_rules',
      'alternate_greetings',
      'primary_system_prompt',
      'opening_message',
      'conditional_entries',
      'extension_hints',
      'structured_outline',
      'vendor_custom_layer',
    ],
  });
  const byId = Object.fromEntries(fullScenario.sections.map(section => [section.id, section]));
  assert.ok(!fullScenario.sections.flatMap(section => section.fixedFields || []).includes('life_profile_json'));
  assert.ok(byId.aiCore.rlFields.includes('scenario'));
  assert.ok(byId.playConfig.fixedFields.includes('affection_rules_json'));
  assert.ok(byId.advanced.collapsed);
  assert.ok(byId.advanced.rlFields.includes('conditional_entries'));
  assert.ok(byId.advanced.rlFields.includes('vendor_custom_layer'));

  const fullIntimate = fields.resolveEditorLayout({
    cardType: 'intimate',
    isBeginnerMode: false,
    availableRlKeys: ['archetype', 'base_profile', 'scenario', 'alternate_greetings'],
  });
  const intimateFields = fullIntimate.sections.flatMap(section => [
    ...(section.fixedFields || []),
    ...(section.rlFields || []),
  ]);
  assert.ok(intimateFields.includes('life_profile_json'));
  assert.ok(intimateFields.includes('archetype'));
  assert.ok(!intimateFields.includes('scenario'));
  assert.ok(!intimateFields.includes('alternate_greetings'));

  assert.deepStrictEqual(
    plain(fields.upsertAffectionMeta('{"compliment":3}', 'scenario_type', 'romance')),
    { compliment: 3, scenario_type: 'romance' }
  );
  assert.deepStrictEqual(
    plain(fields.upsertAffectionMeta('{"scenario_type":"romance","daily_cap":0}', 'scenario_type', '')),
    { daily_cap: 0 }
  );

  assert.strictEqual(fields.validateDangerousRuntimeJson('conditional_entries', '[{"keys":["茶馆"],"content":"设定"}]').ok, true);
  assert.strictEqual(fields.validateDangerousRuntimeJson('extension_hints', '{"depth_prompt":{"prompt":"保持角色","depth":4}}').ok, true);
  assert.strictEqual(fields.validateDangerousRuntimeJson('structured_outline', '{"name":"林深"}').ok, true);
  assert.strictEqual(fields.validateDangerousRuntimeJson('conditional_entries', '{"keys":["错"]}').ok, false);
  assert.strictEqual(fields.validateDangerousRuntimeJson('extension_hints', '[]').ok, false);
  assert.strictEqual(fields.validateDangerousRuntimeJson('structured_outline', '[1]').ok, false);
  assert.strictEqual(fields.validateDangerousRuntimeJson('base_profile', 'not json').ok, true);
  assert.strictEqual(fields.validateAffectionRulesJson('{"enabled":false,"deep_conversation":4}').ok, true);
  assert.strictEqual(fields.validateAffectionRulesJson('[]').ok, false);
  assert.strictEqual(fields.validateAffectionRulesJson('{"events":{"bad":1}}').ok, false);
  assert.strictEqual(fields.validateAffectionRulesJson('{bad').ok, false);

  assert.deepStrictEqual(
    plain(fields.getRiskWarnings({
      cardType: 'scenario',
      lifeProfileJson: '{"basic_info":"不该填"}',
      systemPrompt: '你是林深，温柔陪伴。',
      primarySystemPrompt: '你是旁白，推进冒险。',
      openingMessage: '',
      affectionEnabled: 0,
      affectionRulesJson: '{"enabled":true}',
    })),
    [
      '剧情沙盒不使用人生档案，这段内容保存后不会进入 scenario prompt。',
      '展示字段主指令和运行时优先主指令差异较大，请确认没有互相冲突。',
      '默认开场白为空，用户首次进入时体验会很突兀。',
      '前台状态栏已隐藏，但规则计算仍启用；用户看不到进度变化。',
    ]
  );

  console.log('✅ 管理后台角色编辑字段配置测试全部通过');
})();
