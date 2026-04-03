 const CharDetail = (() => {
   let pendingChar = null;

   function open(char) {
     pendingChar = char;
     const cover = document.getElementById('detail-cover');
     cover.style.background = char.color || 'linear-gradient(135deg,#8a72ff,#ff7eb6)';
     // 优先用 avatarImg（/api/avatar/xxx 路由），和广场页保持一致
     const SERVER_ORIGIN = API_BASE.replace(/\/api$/, '');
     const rawCover = char.coverImg || char.avatarImg || null;
     const imgSrc = rawCover
       ? (rawCover.startsWith('/') ? SERVER_ORIGIN + rawCover : rawCover)
       : null;
     if (imgSrc) {
       cover.style.backgroundImage = `url(${imgSrc})`;
       cover.style.backgroundSize = 'cover';
       cover.style.backgroundPosition = 'center top';
     } else {
       cover.style.backgroundImage = '';
       cover.style.backgroundPosition = '';
     }

     const displayName = char.display_name || char.remark || char.name;
     // 详情页顶部签名：优先 custom_signature，否则用 subtitle（简介），不用旧的 sign 字段
     const signText = char.custom_signature || char.subtitle || '';
     const isAliased = char.remark && char.name && char.remark !== char.name;
     document.getElementById('detail-name').innerHTML = isAliased
       ? `${escapeHtml(displayName)}<div style="font-size:12px;color:rgba(255,255,255,.72);font-weight:500;margin-top:4px;">原名：${escapeHtml(char.name)}</div>`
       : escapeHtml(displayName);
     document.getElementById('detail-sign').textContent = signText;

     // ── 卡类型徽章 ──────────────────────────────────────────────────
     const TYPE_META = {
       intimate:   { icon: '💞', label: '对话陪伴', btnText: '开始聊天 →' },
       scenario:   { icon: '🎭', label: '剧情沙盒', btnText: '进入剧情 →' },
       world:      { icon: '🌐', label: '世界探索', btnText: '进入世界 →' },
       divination: { icon: '🔮', label: '占卜形象', btnText: '开始占卜 →' },
     };
     const cardType = char.card_type || 'intimate';
     const typeMeta = TYPE_META[cardType] || TYPE_META.intimate;

     // 标签行：类型徽章 + 角色原有标签
     const typeBadgeHtml = `<span class="char-detail-tag detail-type-badge ${cardType}">${typeMeta.icon} ${typeMeta.label}</span>`;
     document.getElementById('detail-tags').innerHTML =
       typeBadgeHtml +
       (char.tags || []).map(t => `<span class="char-detail-tag">${t}</span>`).join('');

     // 「关于他」：用 subtitle（自动提取的简短介绍），而不是超长人设档案
     document.getElementById('detail-bio').textContent = char.subtitle || char.bio?.slice(0, 120) || '';

     // ── 开场白预览 ───────────────────────────────────────────────────
     const openingSection = document.getElementById('detail-opening-section');
     const openingEl = document.getElementById('detail-opening');
     const openingText = char.opening_message || char.first_message || '';
     if (openingText && openingText.length > 5) {
       // 最多展示前 200 个字，保持预览简洁
       const previewText = openingText.length > 200 ? openingText.slice(0, 200).trimEnd() + '…' : openingText;
       openingEl.textContent = previewText;
       openingSection.style.display = '';
     } else {
       openingSection.style.display = 'none';
     }

     // 按钮文字根据类型变化
     const chatBtn = document.getElementById('detail-chat-btn');
     if (chatBtn) chatBtn.textContent = typeMeta.btnText;

     document.getElementById('char-detail-modal').classList.add('open');
   }

   function close(e) {
     if (e && e.target !== document.getElementById('char-detail-modal')) return;
     document.getElementById('char-detail-modal').classList.remove('open');
   }

   function startChat() {
     document.getElementById('char-detail-modal').classList.remove('open');
     if (!pendingChar) return;

     // 游客未登录：直接进聊天（用默认开场白，不弹剧情线选择）
     if (!Auth.isLoggedIn()) {
       Chat.enterChat(pendingChar);
       return;
     }

     // 已登录：查询该角色有多少条开场白选项
     API.getGreetings(pendingChar.id).then(result => {
      const greetings = result?.greetings || [];
      if (greetings.length > 1) {
        GreetingSelect.open(pendingChar, greetings);
      } else {
        Chat.enterChat(pendingChar);
      }
    }).catch(function() {
       Chat.enterChat(pendingChar);
     });
   }

   return { open, close, startChat };
 })();
