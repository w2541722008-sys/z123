/**
 * CSP 事件绑定 — 将所有内联 onclick 迁移为 addEventListener。
 *
 * index.html 不再包含任何 onclick 属性，所有交互由本模块集中绑定。
 * 加载时机：在 app.js / auth.js / chat.js 等模块之后，init.js 之前。
 */
;(() => {
  document.addEventListener('DOMContentLoaded', () => {
    // ── 首页按钮 ──
    const homeSquareBtn = document.getElementById('home-square-btn');
    if (homeSquareBtn) homeSquareBtn.addEventListener('click', () => App.nav('square'));

    const homeChatBtn = document.getElementById('home-chat-btn');
    if (homeChatBtn) homeChatBtn.addEventListener('click', () => App.navToLastChat());

    // ── 聊天顶栏 ──
    const chatBackBtn = document.getElementById('chat-back-btn');
    if (chatBackBtn) chatBackBtn.addEventListener('click', () => App.nav('square'));

    const chatMenuToggle = document.getElementById('chat-menu-toggle');
    if (chatMenuToggle) chatMenuToggle.addEventListener('click', () => ChatMenu.toggle());

    // ── 角色状态面板 ──
    const cspHeader = document.getElementById('csp-header');
    if (cspHeader) cspHeader.addEventListener('click', () => Chat.toggleStatusPanel());

    // ── 发送按钮 ──
    const sendBtn = document.getElementById('send-btn');
    if (sendBtn) sendBtn.addEventListener('click', () => Chat.send());

    // ── 登录/登出 ──
    const loginBtn = document.getElementById('login-btn');
    if (loginBtn) loginBtn.addEventListener('click', () => Auth.openLogin());

    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) logoutBtn.addEventListener('click', () => Auth.logout());

    // ── 聊天菜单遮罩 ──
    const chatMenuOverlay = document.getElementById('chat-menu-overlay');
    if (chatMenuOverlay) chatMenuOverlay.addEventListener('click', (e) => ChatMenu.close(e));

    // ── 聊天菜单项 ──
    const menuOpenHistory = document.getElementById('menu-open-history');
    if (menuOpenHistory) menuOpenHistory.addEventListener('click', () => ChatMenu.openHistory());

    const menuClearChat = document.getElementById('menu-clear-chat');
    if (menuClearChat) menuClearChat.addEventListener('click', () => ChatMenu.clearChat());

    const menuOpenRemark = document.getElementById('menu-open-remark');
    if (menuOpenRemark) menuOpenRemark.addEventListener('click', () => ChatMenu.openRemark());

    // ── 聊天记录弹窗 ──
    const historyModal = document.getElementById('history-modal');
    if (historyModal) historyModal.addEventListener('click', (e) => ChatMenu.closeHistory(e));

    const historyCloseBtn = document.getElementById('history-close-btn');
    if (historyCloseBtn) historyCloseBtn.addEventListener('click', () => ChatMenu.closeHistory());

    // ── 修改备注弹窗 ──
    const remarkModal = document.getElementById('remark-modal');
    if (remarkModal) remarkModal.addEventListener('click', (e) => ChatMenu.closeRemark(e));

    const remarkCancelBtn = document.getElementById('remark-cancel-btn');
    if (remarkCancelBtn) remarkCancelBtn.addEventListener('click', () => ChatMenu.closeRemark());

    const remarkSaveBtn = document.getElementById('remark-save-btn');
    if (remarkSaveBtn) remarkSaveBtn.addEventListener('click', () => ChatMenu.saveRemark());

    // ── 登录弹窗 ──
    const loginModal = document.getElementById('login-modal');
    if (loginModal) loginModal.addEventListener('click', (e) => Auth.closeLogin(e));

    const tabLogin = document.getElementById('tab-login');
    if (tabLogin) tabLogin.addEventListener('click', () => Auth.switchTab('login'));

    const tabRegister = document.getElementById('tab-register');
    if (tabRegister) tabRegister.addEventListener('click', () => Auth.switchTab('register'));

    const loginCancelBtn = document.getElementById('login-cancel-btn');
    if (loginCancelBtn) loginCancelBtn.addEventListener('click', () => Auth.closeLogin());

    const authSubmitBtn = document.getElementById('auth-submit-btn');
    if (authSubmitBtn) authSubmitBtn.addEventListener('click', () => Auth.doSubmit());

    // ── 剧情线选择弹窗 ──
    const greetingSelectModal = document.getElementById('greeting-select-modal');
    if (greetingSelectModal) greetingSelectModal.addEventListener('click', (e) => GreetingSelect.close(e));

    const greetingCloseBtn = document.getElementById('greeting-close-btn');
    if (greetingCloseBtn) greetingCloseBtn.addEventListener('click', () => GreetingSelect.close());

    // ── 角色详情弹窗 ──
    const charDetailModal = document.getElementById('char-detail-modal');
    if (charDetailModal) charDetailModal.addEventListener('click', (e) => CharDetail.close(e));

    const detailCloseBtn = document.getElementById('detail-close-btn');
    if (detailCloseBtn) detailCloseBtn.addEventListener('click', () => CharDetail.close());

    const detailChatBtn = document.getElementById('detail-chat-btn');
    if (detailChatBtn) detailChatBtn.addEventListener('click', () => CharDetail.startChat());
  });
})();
