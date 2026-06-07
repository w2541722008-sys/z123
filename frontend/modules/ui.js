const UI = (() => {
  let _toastTimer = null;
  let _queue = [];

  function _showNext() {
    if (_queue.length === 0) return;
    var item = _queue.shift();
    var el = document.getElementById('ui-toast');
    if (!el) { _queue = []; return; }
    el.textContent = item.msg;
    el.className = 'ui-toast' + (item.type ? ' ' + item.type : '');
    void el.offsetWidth;
    el.classList.add('show');
    _toastTimer = setTimeout(function() {
      el.classList.remove('show');
      _toastTimer = null;
      _showNext();
    }, item.duration);
  }

  /**
   * 显示一个轻量 Toast 提示，自动消失。同时段多个调用会排队依次显示。
   * @param {string} msg    - 提示文字
   * @param {'success'|'error'|'warn'|''} type - 颜色类型，默认无色
   * @param {number} duration - 显示时长（ms），默认 2200
   */
  function toast(msg, type = '', duration = 2200) {
    _queue.push({ msg: msg, type: type, duration: duration });
    if (_toastTimer) return; // 当前有 toast 在显示，排队等待
    _showNext();
  }

  /**
   * 显示一个自定义确认弹窗，替代 window.confirm()。
   */
  function confirm(title, body = '', okText = '确认', cancelText = '取消') {
    return new Promise(resolve => {
      const modal    = document.getElementById('confirm-modal');
      const titleEl  = document.getElementById('confirm-title');
      const bodyEl   = document.getElementById('confirm-body');
      const okBtn    = document.getElementById('confirm-ok-btn');
      const cancelBtn= document.getElementById('confirm-cancel-btn');
      if (!modal) { resolve(window.confirm(title + '\n' + body)); return; }

      titleEl.textContent = title;
      bodyEl.textContent  = body;
      okBtn.textContent   = okText;
      cancelBtn.textContent = cancelText;

      modal.classList.add('open');

      function cleanup(result) {
        modal.classList.remove('open');
        okBtn.removeEventListener('click', onOk);
        cancelBtn.removeEventListener('click', onCancel);
        resolve(result);
      }
      function onOk()     { cleanup(true);  }
      function onCancel() { cleanup(false); }
      okBtn.addEventListener('click', onOk);
      cancelBtn.addEventListener('click', onCancel);
    });
  }

  return { toast, confirm };
})();
