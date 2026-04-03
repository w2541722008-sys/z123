var GreetingSelect = (function() {
  var _char = null;

  function open(char, greetings) {
    _char = char;

    var listEl = document.getElementById('greeting-list');
    listEl.innerHTML = '';

    greetings.forEach(function(item) {
      var div = document.createElement('div');
      div.className = 'greeting-item';
      div.setAttribute('data-greeting-index', String(item.index));
      div.innerHTML =
        '<div class="greeting-item-inner">' +
          '<div class="greeting-item-label">' + escapeHtml(item.label) + '</div>' +
          '<div class="greeting-item-preview">' + escapeHtml(item.preview) + '</div>' +
        '</div>' +
        '<span class="greeting-item-arrow">›</span>';

      div.addEventListener('click', function() {
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
    var char = _char;
    close();

    if (!char) {
      if (typeof UI !== 'undefined' && UI.toast) {
        UI.toast('\u89d2\u8272\u4fe1\u606f\u4e22\u5931\uff0c\u8bf7\u91cd\u8bd5', 'error');
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

    safeApiCall(function() {
      return API.clearChatWithGreeting({
        character_id: char.id,
        greeting_index: index,
      });
    }).then(function(result) {
      Chat.enterChat(char);
    }).catch(function(err) {
      if (err && err.message && err.message !== '\u672a\u767b\u5f55') {
        if (typeof UI !== 'undefined' && UI.toast) {
          UI.toast('\u5207\u6362\u5931\u8d25:' + err.message, 'error');
        }
      } else {
        Chat.enterChat(char);
      }
    });
  }

  return { open: open, close: close, select: handleSelect };
})();
