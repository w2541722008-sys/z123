const ADVANCED_GUIDE_META = {
  memories: {
    title: '🧠 这页怎么用：记忆条目',
    desc: '关键词被触发时，内容会被注入到AI的上下文里。它不是聊天记录，而是让AI在特定话题下"想起来"的补充设定。',
    bullets: ['优先放高频会聊到的设定，例如身份背景、关系状态、行为禁忌。', '一条记忆只说一件事，关键词要精准不要贪多。', '如果AI该知道的事却不知道，先来这里测关键词是否命中。']
  },
  categories: {
    title: '🏷️ 这页怎么用：记忆分类',
    desc: '分类只影响后台管理，不会直接改变AI输出。适合记忆条目多了之后，方便你自己整理和查找。',
    bullets: ['可按"身份背景 / 关系状态 / 世界观 / 行为禁忌"来分。', '先保证记忆内容好用，再考虑分类是否漂亮。']
  },
  greetings: {
    title: '👋 这页怎么用：阶段触发语',
    desc: '角色的第一印象和关系升级时的触发语。用户首次进入时说"陌生人"阶段的话，关系升级后下次打开对话时会用对应阶段的话主动找你。',
    bullets: ['至少准备"陌生人 + 朋友"两档，体验会自然很多。', '不同剧情线用不同的开头，不要只是改几个字。', '升级触发语要体现关系变化，比如从客套变亲昵。']
  },
  storylines: {
    title: '📖 这页怎么用：剧情线',
    desc: '把角色的故事拆成几条分支（如校园线/职场线）。它本身不直接说话，但会决定用哪套开场白、后置规则和剧情事件。',
    bullets: ['没有多条分支时，可以先不配。', '一旦配了多条线，必须指定一个默认剧情线。', '剧情线名字要让用户一眼看懂差别，如"校园初遇"vs"职场重逢"。']
  },
  postrules: {
    title: '📝 这页怎么用：后置规则',
    desc: '放在历史记录之后、AI回复之前，作为最后一道约束。适合限制语气、格式和行为边界——不要把角色设定全堆在这里。',
    bullets: ['只写强约束，例如"不要跳出角色""回复保持第一人称"。', '不要把背景设定堆到这里，否则排查时会很痛苦。']
  },
  events: {
    title: '🎭 这页怎么用：剧情事件',
    desc: '好感度达到阈值时自动触发，适合做阶段转换和新内容解锁。建议同时配置"触发时的特殊对话"和"解锁的新内容"。',
    bullets: ['触发文案：事件发生时AI说的话，推进剧情用。', '解锁内容：事件触发后开放的新记忆/开场白/剧情线。', '先做2~3个关键事件，比堆很多空事件更有效。']
  },
  test: {
    title: '🧪 这页怎么用：关键词测试',
    desc: '排查工具：当你怀疑"明明写了设定为什么AI不知道"时，先到这里输入用户真实会发的消息，看能否命中记忆条目。',
    bullets: ['尽量输入真实对话，而不是把关键词堆砌在一起。', '如果测试里都命不中，聊天里大概率也不会命中。']
  }
};

const AFFECTION_BASE_RULES = [
  // 对话陪伴事件
  ['deep_conversation', '深度聊天', 4],
  ['light_chat', '日常轻聊', 1],
  ['compliment', '夸奖赞美', 2],
  ['gift', '送礼物', 6],
  ['help', '主动帮助', 3],
  ['shared_secret', '分享秘密', 5],
  ['first_meeting', '第一次打招呼', 3],
  ['comfort', '安慰对方', 3],
  ['flirt', '调情撒娇', 2],
  ['date', '约会', 5],
  ['first_hug', '第一次拥抱', 7],
  ['kiss', '亲吻', 8],
  ['confession', '表白', 10],
  ['argument', '争吵冲突', -5],
  ['rude', '粗鲁无礼', -3],
  ['ignore', '敷衍忽视', -2],
  ['lie', '说谎被发现', -4],
  ['betray', '背叛', -8],
  ['insult', '侮辱攻击', -6],
];

// 冒险剧情专属事件
const ADVENTURE_AFFECTION_RULES = [
  ['explore', '探索新区域', 2],
  ['discover', '发现线索/物品', 4],
  ['problem_resolved', '解谜成功', 5],
  ['challenge_won', '战斗胜利', 6],
  ['obstacle_cleared', '击败首领', 10],
  ['choice_made', '关键抉择', 3],
  ['npc_helped', '帮助NPC', 3],
  ['secret_found', '发现秘密', 7],
  ['milestone', '达成里程碑', 8],
  ['setback', '战斗失败', -4],
  ['unexpected_danger', '触发陷阱', -3],
  ['relationship_lost', '失去盟友', -6],
  ['opportunity_missed', '错过线索', -2],
];

// 恋爱剧情专属事件
const ROMANCE_AFFECTION_RULES = [
  ['flirt', '调情互动', 2],
  ['date', '约会', 5],
  ['first_hug', '初次拥抱', 7],
  ['kiss', '亲吻', 8],
  ['confession', '告白', 10],
  ['intimate_moment', '亲密时刻', 6],
  ['heartfelt_talk', '真心话', 4],
  ['surprise_gift', '惊喜礼物', 3],
  ['jealousy', '吃醋', -3],
  ['misunderstanding', '误会', -4],
  ['love_rival_appears', '情敌出现', -2],
  ['reconciliation', '和解', 5],
];

// 向后兼容：保留旧的 SCENARIO_AFFECTION_RULES（默认为冒险）
const SCENARIO_AFFECTION_RULES = ADVENTURE_AFFECTION_RULES;
