 /* ================================================================
    渲染角色广场
 ================================================================ */

 function formatTime(date) {
   const h = String(date.getHours()).padStart(2, '0');
   const m = String(date.getMinutes()).padStart(2, '0');
   return `${h}:${m}`;
 }

 function formatDate(date) {
   const days = ['周日','周一','周二','周三','周四','周五','周六'];
   return `${date.getMonth()+1}月${date.getDate()}日 ${days[date.getDay()]}`;
 }

 function formatHistoryTime(value) {
   const date = new Date(value);
   if (Number.isNaN(date.getTime())) return '时间未知';
   return `${formatDate(date)} ${formatTime(date)}`;
 }

function escapeHtml(text = '', options) {
  return window.AIFriendShared.escapeHtml(text, { convertNewlines: true, ...options });
}

function sanitizeCssUrl(url) {
  return window.AIFriendShared.sanitizeCssUrl(url);
}

function normalizeCharTags(tags) {
  if (Array.isArray(tags)) {
    return tags;
  }
  if (typeof tags === 'string') {
    return tags.split(',').map(tag => tag.trim()).filter(Boolean);
  }
  return [];
}

 /* ----------------------------------------------------------------
    toggleSection(key) — 点击分区标题时展开/收起该分区卡片列表
    ---------------------------------------------------------------- */
 function toggleSection(key) {
   const body = document.getElementById(`section-body-${key}`);
   const arrow = document.getElementById(`section-arrow-${key}`);
   const header = document.getElementById(`section-header-${key}`);
   if (!body) return;
   const isOpen = body.classList.toggle('open');
   if (arrow) arrow.textContent = isOpen ? '▲' : '▼';
   if (header) header.classList.toggle('collapsed', !isOpen);
 }

 function renderCharGrid() {
   const grid = document.getElementById('char-grid');
   // 即使角色数据为空，也显示分区结构，只是内容为空

   // ── 推荐横幅（取对话陪伴分组里第一个有封面图的角色）──────────────
   const bannerEl = document.getElementById('featured-banner');
  const featuredChar = CHARACTERS.find(c => (c.card_type || 'intimate') !== 'scenario' && (c.coverImg || c.avatarImg));
   if (bannerEl && featuredChar) {
     const imgSrc = (() => {
       const img = featuredChar.coverImg || featuredChar.avatarImg;
       if (!img) return '';
       return img.startsWith('/') ? SERVER_ORIGIN + img : img;
     })();
     const featuredName = featuredChar.display_name || featuredChar.remark || featuredChar.name || '';
     const featuredSub = featuredChar.subtitle || '';
     const featuredIdx = CHARACTERS.indexOf(featuredChar);
     bannerEl.style.display = '';
     bannerEl.classList.remove('d-none');
     const safeColor = window.AIFriendShared.sanitizeCssColor(featuredChar.color, '#1a1b30');
     const safeImgSrc = escapeHtml(imgSrc || '');
     const safeIdx = featuredIdx;
     bannerEl.innerHTML = `
       <div class="featured-banner-card" data-action="open-char-detail" data-char-idx="${safeIdx}">
         <div class="featured-banner-bg" style="background-color:${safeColor};${safeImgSrc ? `background-image:url('${safeImgSrc}');` : ''}"></div>
         <button class="featured-banner-btn" data-action="enter-chat" data-char-idx="${safeIdx}">立即聊天</button>
         <div class="featured-banner-content">
           <div class="featured-banner-label">✦ 今日推荐</div>
           <div class="featured-banner-name">${escapeHtml(featuredName)}</div>
           ${featuredSub ? `<div class="featured-banner-sub">${escapeHtml(featuredSub)}</div>` : ''}
         </div>
       </div>
     `;
   } else if (bannerEl) {
     bannerEl.style.display = 'none';
   }

   // ── 三分区元信息配置 ──────────────────────────────────────────────
   // key 对应分区 ID，title 是标题，desc 是副标题，gradient 是主题色渐变
  const SECTION_META = {
    intimate: {
      icon: '💞', title: '对话陪伴',
      desc: '专属 AI 角色，沉浸式长期陪伴',
      gradient: 'linear-gradient(90deg, rgba(255,94,158,.18), transparent)',
      accentColor: 'rgba(255,126,182,.8)',
    },
    scenario: {
      icon: '🎭', title: '剧情沙盒',
      desc: '多线分支剧情，解锁角色专属故事线',
      gradient: 'linear-gradient(90deg, rgba(123,92,255,.18), transparent)',
      accentColor: 'rgba(138,114,255,.8)',
    },
  };

  // 卡类型元信息（用于卡片徽章）
  const TYPE_META = {
    intimate:   { icon: '💞', label: '对话陪伴', desc: '专属陪伴' },
    scenario:   { icon: '🎭', label: '剧情沙盒', desc: '多线分支' },
  };

  // 按 card_type 分组：每种类型独立分区
  const groups = { intimate: [], scenario: [] };
  CHARACTERS.forEach((char, i) => {
    if (char.card_type === 'scenario') {
      groups.scenario.push({ char, i });
    } else {
      // 对话陪伴 / 未知 → intimate 分区
      groups.intimate.push({ char, i });
    }
  });

   // ── 渲染单张角色卡片 ─────────────────────────────────────────────
   function renderCard({ char, i }) {
     const cardType = char.card_type || 'intimate';
     const typeMeta = TYPE_META[cardType] || TYPE_META.intimate;
     const displayName = char.display_name || char.remark || char.name;
     const isAliased = char.remark && char.name && char.remark !== char.name;
     const nameHtml = isAliased
       ? `${escapeHtml(displayName)}<small>原名：${escapeHtml(char.name)}</small>`
       : escapeHtml(displayName || '未命名角色');
     const bioText = char.subtitle || (char.bio ? char.bio.slice(0, 80) : '');
    const warningLabel = char.has_import_warning ? `<span class="char-tag warning-tag">需检查</span>` : '';
    const coverStyle = (() => {
       const img = char.coverImg || char.avatarImg;
       if (img) {
         const imgUrl = img.startsWith('/') ? SERVER_ORIGIN + img : img;
         const safeUrl = sanitizeCssUrl(imgUrl);
         return `background:${char.color || 'linear-gradient(135deg,#7b5cff,#ff7eb6)'};${safeUrl ? `background-image:url('${safeUrl}');` : ''}background-size:cover;background-position:center top`;
       }
       return `background:${char.color || 'linear-gradient(135deg,#7b5cff,#ff7eb6)'}`;
     })();

     return `
       <div class="char-card" data-action="open-char-detail" data-char-idx="${i}">
         <div class="char-cover" style="${coverStyle}">
           <span class="type-badge ${cardType}">${typeMeta.icon} ${typeMeta.label}</span>
           ${char.free ? '<span class="free-badge">免费</span>' : ''}
         </div>
         <div class="char-info" style="padding:10px 12px 12px">
           <div class="char-name">${nameHtml}</div>
           <div class="char-bio">${escapeHtml(bioText || '暂无简介')}</div>
           <div class="char-tags" style="margin-top:8px">
             ${warningLabel}
             ${normalizeCharTags(char.tags).slice(0,2).map(t => `<span class="char-tag">${escapeHtml(t)}</span>`).join('')}
           </div>
         </div>
       </div>
     `;
   }

  // ── 渲染可折叠分区（手风琴样式）────────────────────────────────
  function renderCollapsibleSection(key, items, extraCards = '', defaultOpen = false) {
    const meta = SECTION_META[key];
    const realCount = items.length;
    const openClass = defaultOpen ? 'open' : '';
    const arrowChar = defaultOpen ? '▲' : '▼';
    const cardsHtml = items.map(renderCard).join('') + extraCards;
    
    // 空状态提示
    const emptyHtml = cardsHtml ? '' : `
      <div style="padding: 32px 20px; text-align: center; color: var(--muted); font-size: 14px;">
        <div style="font-size: 32px; margin-bottom: 12px; opacity: 0.5;">${meta.icon}</div>
        <div>暂无${meta.title}角色</div>
        <div style="font-size: 12px; margin-top: 6px; opacity: 0.7;">敬请期待后续更新</div>
      </div>
    `;

    return `
      <div class="square-accordion">
        <!-- 可点击的分区标题行 -->
        <div
          id="section-header-${key}"
          class="accordion-header ${openClass ? '' : 'collapsed'}"
          data-action="toggle-section" data-section="${key}"
          style="--accent:${meta.accentColor};--gradient:${meta.gradient}"
        >
          <div class="accordion-header-left">
            <span class="accordion-icon">${meta.icon}</span>
            <div class="accordion-title-block">
              <span class="accordion-title">${meta.title}</span>
              <span class="accordion-desc">${meta.desc}</span>
            </div>
          </div>
          <div class="accordion-header-right">
            <span class="accordion-count">${realCount} 个</span>
            <span id="section-arrow-${key}" class="accordion-arrow">${arrowChar}</span>
          </div>
        </div>

        <!-- 可折叠的卡片区域 -->
        <div id="section-body-${key}" class="accordion-body ${openClass}">
          <div class="accordion-cards-grid">
            ${cardsHtml || emptyHtml}
          </div>
        </div>
      </div>
    `;
  }

  // 拼装两个分区
  grid.classList.remove('single-section'); // 多分区模式不需要此 class
  grid.innerHTML =
    renderCollapsibleSection('intimate',   groups.intimate,   '', false) +
    renderCollapsibleSection('scenario',   groups.scenario,   '', false);

}
