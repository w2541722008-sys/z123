 const App = (() => {
   let currentPage = 'home';

   function renderNav() {
     const nav = document.getElementById('bottom-nav');
     if (!nav) return;
     nav.innerHTML = NAV_CONFIG.map(item => `
       <div class="nav-item${item.id === currentPage ? ' active' : ''}"
            data-page="${item.id}"
            onclick="App.nav('${item.id}')">
         <span class="nav-icon">${item.icon}</span>
         <span>${item.label}</span>
       </div>
     `).join('');
   }

   function nav(pageId) {
    if (pageId === 'chat' && !Chat.currentChar) {
      // 尝试恢复上次聊天的角色
      const lastCharacterId = AppState.getLastCharacterId();
      const found = CHARACTERS.find(item => item.id === lastCharacterId);
      
      if (found) {
        Chat.enterChat(found);
        return;
      }
      
      // 角色不存在，跳转到角色选择页
      nav('square');
      return;
    }
    document.querySelectorAll('.page').forEach(p => {
      p.classList.toggle('active', p.id === `page-${pageId}`);
    });
    currentPage = pageId;
    renderNav();
    if (pageId !== 'chat') {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }

   function navToLastChat() {
     const lastCharacterId = AppState.getLastCharacterId();
     const found = CHARACTERS.find(item => item.id === lastCharacterId);
     if (found) {
       Chat.enterChat(found);
       return;
     }
     nav('square');
   }

  function preloadCharacterImages(characters) {
    const loaded = new Set();
    characters.forEach(char => {
      [char.avatarImg, char.coverImg].forEach(img => {
        if (!img || loaded.has(img)) return;
        loaded.add(img);
        const url = img.startsWith('/') ? SERVER_ORIGIN + img : img;
        const i = new Image();
        i.src = url;
      });
    });
  }

  async function init() {
     renderNav();
     await loadCharacters();
     Auth.bootstrap();
   }

   async function loadCharacters() {
    try {
      const characters = await API.getCharacters();
      CHARACTERS = characters;
      renderCharGrid();
      preloadCharacterImages(characters);
    } catch (err) {
       document.getElementById('char-grid').innerHTML = `
         <div class="card" style="padding:16px;color:var(--muted);grid-column:1 / -1;">
           角色加载失败：${err.message}<br/>请先启动本地后端，再刷新页面。
         </div>
       `;
     }
   }

   return {
     nav,
     navToLastChat,
     init,
     loadCharacters,
     get currentPage() { return currentPage; },
   };
 })();
