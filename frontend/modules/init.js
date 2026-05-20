(() => {
  document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('chat-input');
    if (!input) return;

    // 输入框高度自适应（使用 requestAnimationFrame 优化性能）
    let rafId = null;
    input.addEventListener('input', () => {
      if (rafId) cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
      });
    });

    // 键盘发送支持
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        Chat.send();
      }
    });

    // iOS 键盘适配优化
    const chatPage = document.getElementById('page-chat');
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);

    function onViewportResize() {
      if (!window.visualViewport) return;
      const vvh = window.visualViewport.height;
      const diff = window.innerHeight - vvh;

      if (chatPage) {
        if (diff > 100) {
          chatPage.style.paddingBottom = `${diff + 20}px`;
          const box = document.getElementById('chat-messages');
          if (box) {
            requestAnimationFrame(() => {
              box.scrollTop = box.scrollHeight;
            });
          }
        } else {
          chatPage.style.paddingBottom = '';
        }
      }
    }

    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', onViewportResize, { passive: true });
    }

    // 聚焦时滚动优化（iOS 需要延迟）
    input.addEventListener('focus', () => {
      if (isIOS) {
        setTimeout(() => {
          const box = document.getElementById('chat-messages');
          if (box) box.scrollTop = box.scrollHeight;
          input.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }, 300);
      }
    });

    // 对交互控件禁用双击缩放
    const zoomStyle = document.createElement('style');
    zoomStyle.textContent = '#chat-input, #send-btn, button, .msg-row, .greeting-card, .character-card { touch-action: manipulation; }';
    document.head.appendChild(zoomStyle);

    // 头像上传
    const avatarInput = document.getElementById('avatar-file-input');
    if (avatarInput) {
      avatarInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;
        if (file.size > 2 * 1024 * 1024) { UI.toast('图片大小不能超过 2MB', 'warn'); return; }
        const allowedTypes = ['image/jpeg', 'image/png', 'image/webp'];
        if (!allowedTypes.includes(file.type)) { UI.toast('仅支持 JPG、PNG、WebP 格式', 'warn'); return; }
        Auth.uploadAvatar(file);
        avatarInput.value = '';
      });
    }
  });

  App.init();
})();
