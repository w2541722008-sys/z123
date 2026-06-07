 const CharDetail = (() => {
   let pendingChar = null;

   function open(char) {
     pendingChar = char;
     const cover = document.getElementById('detail-cover');
     const rawColor = char.color || 'linear-gradient(135deg,#8a72ff,#ff7eb6)';
     // CSS 注入防护：拒绝含 url() 或 javascript: 的值
     cover.style.background = /url\(|javascript:/i.test(rawColor) ? 'linear-gradient(135deg,#8a72ff,#ff7eb6)' : rawColor;
    // 优先用 avatarImg（/api/avatar/xxx 路由），和广场页保持一致
    const rawCover = char.coverImg || char.avatarImg || null;
     const imgSrc = rawCover
       ? (rawCover.startsWith('/') ? SERVER_ORIGIN + rawCover : rawCover)
       : null;
     if (imgSrc) {
      // 使用 sanitizeCssUrl 安全设置 URL，避免 CSS 注入
      const safeImgSrc = window.AIFriendShared.sanitizeCssUrl(imgSrc);
      if (safeImgSrc) {
        cover.style.backgroundImage = `url('${safeImgSrc}')`;
      }
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
    };
     const cardType = char.card_type || 'intimate';
     const typeMeta = TYPE_META[cardType] || TYPE_META.intimate;

     // 标签行：类型徽章 + 角色原有标签（使用 textContent 安全渲染）
    const tagsContainer = document.getElementById('detail-tags');
    tagsContainer.innerHTML = '';
    
    const typeBadge = document.createElement('span');
    typeBadge.className = `char-detail-tag detail-type-badge ${cardType}`;
    typeBadge.textContent = `${typeMeta.icon} ${typeMeta.label}`;
    tagsContainer.appendChild(typeBadge);
    
    (char.tags || []).forEach(t => {
      const tag = document.createElement('span');
      tag.className = 'char-detail-tag';
      tag.textContent = t;
      tagsContainer.appendChild(tag);
    });

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
       openingSection.classList.remove('d-none');
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

    if (!Auth.isLoggedIn()) {
      Chat.enterChat(pendingChar);
      return;
    }

    // 并行查询历史和开场白，减少等待时间
    Promise.all([
      API.getHistory(pendingChar.id).catch(function() { return null; }),
      API.getGreetings(pendingChar.id).catch(function() { return null; })
    ]).then(function(_ref) {
      var historyResult = _ref[0];
      var greetResult = _ref[1];
      var messages = (historyResult && historyResult.messages) || [];
      if (messages.length > 0) {
        Chat.enterChat(pendingChar);
      } else {
        var greetings = (greetResult && greetResult.greetings) || [];
        if (greetings.length > 1) {
          GreetingSelect.open(pendingChar, greetings);
        } else {
          Chat.enterChat(pendingChar);
        }
      }
    }).catch(function() {
      Chat.enterChat(pendingChar);
    });
  }

   return { open, close, startChat };
 })();
