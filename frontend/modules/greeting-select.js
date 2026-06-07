const GreetingSelect = (() => {
  let _char = null;

  function open(char, greetings) {
    _char = char;

    const listEl = document.getElementById('greeting-list');
    listEl.innerHTML = '';

    greetings.forEach((item) => {
      const div = document.createElement('div');
      div.className = 'greeting-item';
      div.setAttribute('data-greeting-index', String(item.index));
      div.innerHTML =
        '<div class="greeting-item-inner">' +
          '<div class="greeting-item-label">' + escapeHtml(item.label) + '</div>' +
          '<div class="greeting-item-preview">' + escapeHtml(item.preview) + '</div>' +
        '</div>' +
        '<span class="greeting-item-arrow">›</span>';

      div.addEventListener('click', () => {
        handleSelect(item.index);
      });

      listEl.appendChild(div);
    });

    document.getElementById('greeting-select-modal').classList.add('open');
  }

  function close(e) {
    if (e && e.target !== document.getElementById('greeting-select-modal')) return;
    document.getElementById('greeting-select-modal').classList.remove('open');
  }

  function handleSelect(index) {
    const char = _char;
    close();

    if (!char) {
      if (typeof UI !== 'undefined' && UI.toast) {
        UI.toast('角色信息丢失，请重试', 'error');
      }
      return;
    }

    if (index === 0) {
      Chat.enterChat(char);
      return;
    }

    if (typeof safeApiCall === 'undefined') {
      Chat.enterChat(char);
      return;
    }

    safeApiCall(() => {
      return API.clearChatWithGreeting({
        character_id: char.id,
        greeting_index: index,
      });
    }).then(() => {
      Chat.enterChat(char);
    }).catch((err) => {
      const msg = (err && err.message) ? err.message : JSON.stringify(err);
      if (msg && msg !== '未登录') {
        if (typeof UI !== 'undefined' && UI.toast) {
          UI.toast('切换失败:' + msg, 'error');
        }
      }
      Chat.enterChat(char);
    });
  }

  return { open, close, select: handleSelect };
})();
