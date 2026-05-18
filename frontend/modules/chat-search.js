/** chat-search.js — 聊天消息全文搜索面板 */
const ChatSearch = (() => {
  let _panel = null;
  let _debounceTimer = null;
  let _currentQuery = '';
  let _currentPage = 1;
  let _characterId = '';

  /* ── 面板生命周期 ──────────────────────────────────────── */
  function open(characterId) {
    _characterId = characterId;
    _currentPage = 1;
    _currentQuery = '';
    _ensurePanel();
    _panel.classList.add('show');
    var input = _panel.querySelector('.chat-search-input');
    input.value = '';
    setTimeout(function () { input.focus(); }, 150);
    _showInitialState();
  }

  function close() {
    if (_panel) _panel.classList.remove('show');
  }

  /* ── DOM 构建 ──────────────────────────────────────────── */
  function _ensurePanel() {
    if (_panel) return;
    _panel = document.createElement('div');
    _panel.className = 'chat-search-overlay';
    _panel.innerHTML =
      '<div class="chat-search-panel">' +
        '<div class="chat-search-header">' +
          '<span class="chat-search-back">←</span>' +
          '<input class="chat-search-input" type="text" placeholder="搜索聊天记录…" autocomplete="off" enterkeyhint="search">' +
        '</div>' +
        '<div class="chat-search-body" id="chat-search-body"></div>' +
      '</div>';
    document.body.appendChild(_panel);

    _panel.querySelector('.chat-search-back').onclick = close;
    var input = _panel.querySelector('.chat-search-input');
    input.oninput = _onInput;
    input.onkeydown = function (e) { if (e.key === 'Enter') { e.preventDefault(); _triggerSearch(); } };
    _panel.addEventListener('click', function (e) { if (e.target === _panel) close(); });
  }

  function _showInitialState() {
    var body = document.getElementById('chat-search-body');
    if (body) body.innerHTML = '<div class="chat-search-hint">输入关键词搜索聊天记录</div>';
  }

  /* ── 搜索逻辑 ──────────────────────────────────────────── */
  function _onInput() {
    var input = _panel.querySelector('.chat-search-input');
    var q = (input.value || '').trim();
    clearTimeout(_debounceTimer);
    if (!q) { _showInitialState(); return; }
    _debounceTimer = setTimeout(function () { _doSearch(q); }, 300);
  }

  function _triggerSearch() {
    clearTimeout(_debounceTimer);
    var input = _panel.querySelector('.chat-search-input');
    var q = (input.value || '').trim();
    if (q) _doSearch(q);
  }

  function _doSearch(q) {
    _currentQuery = q;
    _currentPage = 1;
    var body = document.getElementById('chat-search-body');
    if (body) body.innerHTML = '<div class="chat-search-loading">搜索中…</div>';
    API.searchMessages(q, _characterId, 1).then(function (result) {
      _renderResults(result);
    }).catch(function (err) {
      var body2 = document.getElementById('chat-search-body');
      if (body2) body2.innerHTML = '<div class="chat-search-error">搜索失败：' + escapeHtml(err.message || '网络错误') + '</div>';
    });
  }

  function _loadMore() {
    _currentPage++;
    var moreBtn = document.getElementById('chat-search-more');
    if (moreBtn) moreBtn.textContent = '加载中…';
    API.searchMessages(_currentQuery, _characterId, _currentPage).then(function (result) {
      _appendResults(result);
    }).catch(function () {
      if (moreBtn) moreBtn.textContent = '加载失败，点击重试';
    });
  }

  /* ── 时间格式化 ────────────────────────────────────────── */
  function _formatTime(dateStr) {
    var d = new Date(dateStr);
    var h = String(d.getHours()).padStart(2, '0');
    var m = String(d.getMinutes()).padStart(2, '0');
    var time = h + ':' + m;
    var now = new Date();
    if (d.toDateString() === now.toDateString()) return time;
    var y = new Date(now);
    y.setDate(y.getDate() - 1);
    if (d.toDateString() === y.toDateString()) return '昨天 ' + time;
    return (d.getMonth() + 1) + '月' + d.getDate() + '日 ' + time;
  }

  /* ── 结果构建 ──────────────────────────────────────────── */
  function _buildResultItem(r) {
    var roleLabel = r.role === 'user' ? '你' : '角色';
    var fullText = r.content || '';
    var preview = fullText.replace(/\n/g, ' ').slice(0, 200);
    var needsFold = fullText.length > 200;
    return (
      '<div class="chat-search-item" data-id="' + escapeHtml(String(r.id)) + '" data-full="' + escapeHtml(fullText) + '">' +
        '<div class="chat-search-item-meta">' +
          '<span class="chat-search-role">' + escapeHtml(roleLabel) + '</span>' +
          '<span class="chat-search-time">' + escapeHtml(_formatTime(r.created_at)) + '</span>' +
        '</div>' +
        '<div class="chat-search-item-text">' + escapeHtml(preview) + '</div>' +
        (needsFold ? '<div class="chat-search-item-fold">展开查看完整内容</div>' : '') +
        '<div class="chat-search-item-full" style="display:none">' + escapeHtml(fullText).replace(/\n/g, '<br>') + '</div>' +
      '</div>'
    );
  }

  function _renderResults(result) {
    var body = document.getElementById('chat-search-body');
    if (!body) return;
    var items = result.results || [];
    var total = result.total || 0;
    if (items.length === 0) {
      body.innerHTML = '<div class="chat-search-empty">未找到相关消息</div>';
      return;
    }
    var html = '<div class="chat-search-summary">找到 ' + total + ' 条结果</div>';
    for (var i = 0; i < items.length; i++) {
      html += _buildResultItem(items[i]);
    }
    if (result.has_more) {
      html += '<div class="chat-search-more" id="chat-search-more">加载更多结果</div>';
    }
    body.innerHTML = html;
    _bindItemClicks(body);
    var moreBtn = document.getElementById('chat-search-more');
    if (moreBtn) moreBtn.onclick = _loadMore;
  }

  function _appendResults(result) {
    var body = document.getElementById('chat-search-body');
    if (!body) return;
    var moreBtn = document.getElementById('chat-search-more');
    if (moreBtn) moreBtn.remove();
    var items = result.results || [];
    for (var i = 0; i < items.length; i++) {
      var div = document.createElement('div');
      div.className = 'chat-search-item';
      div.dataset.id = items[i].id;
      var fullText = items[i].content || '';
      var preview = fullText.replace(/\n/g, ' ').slice(0, 200);
      var needsFold = fullText.length > 200;
      div.innerHTML =
        '<div class="chat-search-item-meta">' +
          '<span class="chat-search-role">' + escapeHtml(items[i].role === 'user' ? '你' : '角色') + '</span>' +
          '<span class="chat-search-time">' + escapeHtml(_formatTime(items[i].created_at)) + '</span>' +
        '</div>' +
        '<div class="chat-search-item-text">' + escapeHtml(preview) + '</div>' +
        (needsFold ? '<div class="chat-search-item-fold">展开查看完整内容</div>' : '') +
        '<div class="chat-search-item-full" style="display:none">' + escapeHtml(fullText).replace(/\n/g, '<br>') + '</div>';
      div.dataset.full = fullText;
      div.onclick = _onItemClick;
      body.appendChild(div);
    }
    if (result.has_more) {
      var btn = document.createElement('div');
      btn.className = 'chat-search-more';
      btn.id = 'chat-search-more';
      btn.textContent = '加载更多结果';
      btn.onclick = _loadMore;
      body.appendChild(btn);
    }
  }

  function _bindItemClicks(container) {
    var items = container.querySelectorAll('.chat-search-item');
    for (var i = 0; i < items.length; i++) {
      items[i].onclick = _onItemClick;
    }
  }

  /* ── 展开/折叠 ────────────────────────────────────────── */
  function _onItemClick(e) {
    // 如果点击的是已展开的完整内容区域，不处理（允许用户选择文字）
    if (e && e.target && e.target.closest && e.target.closest('.chat-search-item-full')) return;
    var wasExpanded = this.classList.contains('expanded');
    // 折叠所有其他项
    var allItems = document.querySelectorAll('.chat-search-item.expanded');
    for (var i = 0; i < allItems.length; i++) allItems[i].classList.remove('expanded');
    if (!wasExpanded) this.classList.add('expanded');
  }

  return { open: open, close: close };
})();
