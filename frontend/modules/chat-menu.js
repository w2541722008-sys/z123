 const ChatMenu = (() => {
   function ensureCurrentChar() {
     if (!Chat.currentChar) {
       UI.toast('请先进入一个角色聊天页。', 'warn');
       return false;
     }
     return true;
   }

   function toggle() {
     if (!ensureCurrentChar()) return;
     document.getElementById('chat-menu-overlay').classList.toggle('open');
   }

   function close(e) {
     if (e && e.target !== document.getElementById('chat-menu-overlay')) return;
     document.getElementById('chat-menu-overlay').classList.remove('open');
   }

   function renderHistoryModal() {
     const listEl = document.getElementById('history-list');
     const messages = Chat.history || [];
     if (!messages.length) {
       listEl.innerHTML = `<div class="history-empty">现在还没有聊天记录，等你们开始说话后，这里就会慢慢填满。</div>`;
       return;
     }
     const meta = Chat.getDisplayMeta();
     listEl.innerHTML = messages.map(item => `
       <div class="history-card" style="content-visibility:auto;contain-intrinsic-size:auto 80px">
         <div class="history-role ${item.role === 'user' ? 'user' : ''}">${item.role === 'user' ? '你' : escapeHtml(meta.displayName)}</div>
         <div class="history-content">${escapeHtml((item.content || '').slice(0, 300))}${(item.content || '').length > 300 ? '…' : ''}</div>
         <div class="history-time">${item.created_at ? formatHistoryTime(item.created_at) : '刚刚'}</div>
       </div>
     `).join('');
   }

   function openHistory() {
     close();
     if (!ensureCurrentChar()) return;
     renderHistoryModal();
     document.getElementById('history-modal').classList.add('open');
   }

   function closeHistory(e) {
     if (e && e.target !== document.getElementById('history-modal')) return;
     document.getElementById('history-modal').classList.remove('open');
   }

   function openRemark() {
     close();
     if (!ensureCurrentChar()) return;
     document.getElementById('input-remark').value = Chat.currentChar?.remark || '';
     document.getElementById('remark-modal').classList.add('open');
   }

   function closeRemark(e) {
     if (e && e.target !== document.getElementById('remark-modal')) return;
     document.getElementById('remark-modal').classList.remove('open');
   }

   async function saveRemark() {
     if (!ensureCurrentChar()) return;
     const remark = document.getElementById('input-remark').value.trim();
     try {
       const result = await safeApiCall(() => API.updateCharacterProfile({
         character_id: Chat.currentChar.id,
         remark,
         custom_signature: Chat.currentChar.custom_signature || '',
       }));
       Chat.applyCharacterProfile(result.character);
       closeRemark();
       UI.toast(remark ? '备注已保存。' : '备注已清空。', 'success');
     } catch (err) {
       if (err.message !== '未登录') UI.toast(`保存失败：${err.message}`, 'error');
     }
   }

   async function clearChat() {
     close();
     if (!ensureCurrentChar()) return;
     const meta = Chat.getDisplayMeta();
    const ok = await UI.confirm(
      `清空与${meta.displayName}的聊天记录`,
      `清空后一切将从零开始（包括关系状态、好感度、剧情进度），当前的聊天记录将无法恢复。`,
      '确认清空',
      '再想想'
    );
     if (!ok) return;
     try {
       // 先清空聊天记录（用默认开场白占位）
       await safeApiCall(() => API.clearChatWithGreeting({ character_id: Chat.currentChar.id, greeting_index: -1 }));

       // 查 greetings，有多条时让用户重选剧情线
       const result = await API.getGreetings(Chat.currentChar.id).catch(() => null);
       const greetings = result?.greetings || [];
       if (greetings.length > 1) {
         GreetingSelect.open(Chat.currentChar, greetings);
       } else {
         await Chat.enterChat(Chat.currentChar);
         UI.toast('聊天记录已清空，重新开始了。', 'success');
       }
     } catch (err) {
       if (err.message !== '未登录') UI.toast(`清空失败：${err.message}`, 'error');
     }
   }

   return {
     toggle,
     close,
     openHistory,
     closeHistory,
     openRemark,
     closeRemark,
     saveRemark,
     clearChat,
   };
 })();
