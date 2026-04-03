const UI = (() => {
  let _toastTimer = null;

  /**
   * 显示一个轻量 Toast 提示，自动消失。
   * @param {string} msg    - 提示文字
   * @param {'success'|'error'|'warn'|''} type - 颜色类型，默认无色
   * @param {number} duration - 显示时长（ms），默认 2200
   */
  function toast(msg, type = '', duration = 2200) {
    const el = document.getElementById('ui-toast');
    if (!el) return;
    // 清除上一个 timer，实现连续 toast 时重置
    if (_toastTimer) clearTimeout(_toastTimer);
    el.textContent = msg;
    el.className = 'ui-toast' + (type ? ' ' + type : '');
    // 强制回流后再加 show，确保过渡动画触发
    void el.offsetWidth;
    el.classList.add('show');
    _toastTimer = setTimeout(() => {
      el.classList.remove('show');
      _toastTimer = null;
    }, duration);
  }

  /**
   * 显示一个自定义确认弹窗，替代 window.confirm()。
   * 返回 Promise<boolean>，用户点确认 resolve(true)，点取消 resolve(false)。
   * @param {string} title   - 弹窗标题（粗体）
   * @param {string} body    - 说明文字（可含换行）
   * @param {string} okText  - 确认按钮文字，默认"确认"
   * @param {string} cancelText - 取消按钮文字，默认"取消"
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
