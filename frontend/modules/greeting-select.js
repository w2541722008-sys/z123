var GreetingSelect = (function() {
  var _char = null;
  var _greetings = [];
  var _bound = false;

  function open(char, greetings) {
    _char = char;
    _greetings = greetings;

    var listEl = document.getElementById('greeting-list');
    listEl.innerHTML = greetings.map(function(item) {
      return '<div class="greeting-item" data-greeting-index="' + item.index + '">' +
        '<div class="greeting-item-inner">' +
          '<div class="greeting-item-label">' + escapeHtml(item.label) + '</div>' +
          '<div class="greeting-item-preview">' + escapeHtml(item.preview) + '</div>' +
        '</div>' +
        '<span class="greeting-item-arrow">›</span>' +
      '</div>';
    }).join('');

    ensureClickDelegate();
    document.getElementById('greeting-select-modal').classList.add('open');
  }

  function close(e) {
    if (e && e.target !== document.getElementById('greeting-select-modal')) return;
    document.getElementById('greeting-select-modal').classList.remove('open');
  }

  function onItemClick(e) {
    var item = e.target.closest ? e.target.closest('.greeting-item') : e.target;
    if (!item || !item.classList) return;
    if (!item.classList.contains('greeting-item')) {
      while (item && item !== e.currentTarget) {
        item = item.parentNode;
        if (item && item.classList && item.classList.contains('greeting-item')) break;
      }
    }
    if (!item || !item.classList || !item.classList.contains('greeting-item')) return;
    var index = Number(item.getAttribute('data-greeting-index'));
    if (!isNaN(index)) {
      select(index);
    }
  }

  function ensureClickDelegate() {
    if (_bound) return;
    _bound = true;
    var listEl = document.getElementById('greeting-list');
    if (listEl) {
      listEl.addEventListener('click', onItemClick);
    }
  }

  async function select(index) {
    close();
    if (!_char) return;

    var char = _char;

    if (index === 0) {
      Chat.enterChat(char);
      return;
    }

    try {
      await safeApiCall(function() {
        return API.clearChatWithGreeting({
          character_id: char.id,
          greeting_index: index,
        });
      });
    } catch (err) {
      if (err.message !== '\u672a\u767b\u5f55') {
        UI.toast('\u5207\u6362\u5267\u60c5\u7ebf\u5931\u8d25\uff1a' + err.message, 'error');
      }
      return;
    }

    Chat.enterChat(char);
  }

  return { open: open, close: close, select: select };
})();
