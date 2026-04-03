 const GreetingSelect = (() => {
   let _char = null;     // 当前待进入的角色
   let _greetings = [];  // 开场白选项列表

   /**
    * 打开剧情线选择弹窗。
    * @param {object} char      - 角色对象
    * @param {Array}  greetings - 后端返回的 greetings 数组
    */
   function open(char, greetings) {
     _char = char;
     _greetings = greetings;

     // 渲染选项列表
     const listEl = document.getElementById('greeting-list');
     listEl.innerHTML = greetings.map(item => `
       <div class="greeting-item" onclick="GreetingSelect.select(${item.index})">
         <div class="greeting-item-inner">
           <div class="greeting-item-label">${escapeHtml(item.label)}</div>
           <div class="greeting-item-preview">${escapeHtml(item.preview)}</div>
         </div>
         <span class="greeting-item-arrow">›</span>
       </div>
     `).join('');

     document.getElementById('greeting-select-modal').classList.add('open');
   }

   function close(e) {
     if (e && e.target !== document.getElementById('greeting-select-modal')) return;
     document.getElementById('greeting-select-modal').classList.remove('open');
   }

   /**
    * 用户选择了某条剧情线。
    * - 若 index=0（默认），直接进入聊天（无需清空，走正常流程即可）
    * - 若 index>=1（alternate），先调清空接口指定 greeting_index，再进入聊天
    * @param {number} index - greetings 中的 index 字段
    */
   async function select(index) {
     close();
     if (!_char) return;

     const char = _char;

     if (index === 0) {
       Chat.enterChat(char);
       return;
     }

     // 非默认剧情线：先重置聊天并用指定开场白，再进入聊天页
     // （游客不应能走到这里，已在 startChat 里处理）
     try {
       await safeApiCall(() => API.clearChatWithGreeting({
         character_id: char.id,
         greeting_index: index,
       }));
     } catch (err) {
       if (err.message !== '未登录') {
         UI.toast(`切换剧情线失败：${err.message}`, 'error');
       }
       return;
     }

     Chat.enterChat(char);
   }

   return { open, close, select };
 })();
