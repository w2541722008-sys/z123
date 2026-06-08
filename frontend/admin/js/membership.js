/**
 * membership.js - 会员管理标签页逻辑
 *
 * 包含：用户列表、订单列表、用户详情/编辑弹窗、批量操作、CSV 导出。
 * 依赖：utils.js, api.js, state.js
 */

// ============================================================
// 数据加载
// ============================================================
async function loadMembershipData() {
  const usersWrap = document.getElementById('membership-users-table-wrap');
  const ordersWrap = document.getElementById('membership-orders-table-wrap');
  if (!usersWrap || !ordersWrap) return;
  usersWrap.innerHTML = skeletonHtml(0, 5);
  ordersWrap.innerHTML = skeletonHtml(0, 5);

  const userSearch = document.getElementById('user-search')?.value || '';
  const userPlan = document.getElementById('user-plan-filter')?.value || '';
  const orderSearch = document.getElementById('order-search')?.value || '';
  const orderStatus = document.getElementById('order-status-filter')?.value || '';

  try {
    const md = AdminState.membershipData;
    const [usersRes, ordersRes] = await Promise.all([
      AdminAPI.apiFetch(`${AdminAPI.API}/users?search=${encodeURIComponent(userSearch)}&plan=${encodeURIComponent(userPlan)}&page=${md.usersPage}&limit=${md.usersLimit}`),
      AdminAPI.apiFetch(`${AdminAPI.API}/orders?search=${encodeURIComponent(orderSearch)}&status=${encodeURIComponent(orderStatus)}&page=${md.ordersPage}&limit=${md.ordersLimit}`),
    ]);
    md.users = usersRes.items || [];
    md.usersTotal = usersRes.total || 0;
    md.orders = ordersRes.orders || [];
    md.ordersTotal = ordersRes.total || 0;
    renderMembershipUsers();
    renderMembershipOrders();
  } catch (e) {
    usersWrap.innerHTML = `<div class="no-results" style="color:#f87171">加载失败：${escHtml(e.message)}</div>`;
    ordersWrap.innerHTML = `<div class="no-results" style="color:#f87171">加载失败：${escHtml(e.message)}</div>`;
  }
}

function filterUsers() {
  AdminState.membershipData.usersPage = 1;
  AdminState.membershipData.selectedUserIds.clear();
  clearUserSelection();
  loadMembershipData();
}

function filterOrders() {
  AdminState.membershipData.ordersPage = 1;
  loadMembershipData();
}

// ============================================================
// 子标签页切换
// ============================================================
function switchMembershipSubtab(tab) {
  document.querySelectorAll('.sub-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.subTab === tab);
  });
  document.querySelectorAll('.sub-tab-panel').forEach(panel => {
    panel.style.display = 'none';
  });
  const target = document.getElementById('sub-tab-' + tab);
  if (target) target.style.display = '';
}

// 防抖版本的搜索函数（400ms 延迟，避免每敲一个字符就请求一次）
const debouncedFilterUsers = debounce(filterUsers, 400);
const debouncedFilterOrders = debounce(filterOrders, 400);

// ============================================================
// 用户列表渲染
// ============================================================
function renderMembershipUsers() {
  const box = document.getElementById('membership-users-table-wrap');
  const countLabel = document.getElementById('user-count-label');
  const pagerEl = document.getElementById('user-pager');
  if (!box) return;

  const md = AdminState.membershipData;
  const users = md.users;
  const total = md.usersTotal;
  const page = md.usersPage;
  const limit = md.usersLimit;
  const totalPages = Math.ceil(total / limit);

  if (countLabel) countLabel.textContent = `共 ${total} 位用户`;

  if (!users.length) {
    box.innerHTML = '<div class="no-results">暂无用户数据</div>';
    if (pagerEl) pagerEl.innerHTML = '';
    return;
  }

  box.innerHTML = `
    <div class="table-scroll">
    <table class="user-table">
      <thead>
        <tr>
          <th style="width:32px"><input type="checkbox" class="user-checkbox" id="user-check-all" data-user-check-all="true" /></th>
          <th>ID</th>
          <th>昵称</th>
          <th>邮箱</th>
          <th>档位</th>
          <th>注册时间</th>
          <th>到期时间</th>
          <th style="text-align:right">操作</th>
        </tr>
      </thead>
      <tbody>
        ${users.map(u => `
          <tr>
            <td><input type="checkbox" class="user-checkbox" value="${escHtml(String(u.id))}" data-user-select="true" ${md.selectedUserIds.has(u.id) ? 'checked' : ''} /></td>
            <td class="col-id">#${u.id}</td>
            <td><strong>${escHtml(u.nickname || '—')}</strong></td>
            <td class="col-email">${escHtml(u.email || '—')}</td>
            <td><span class="badge badge-${u.effective_plan || 'free'}">${escHtml(formatPlanLabel(u.effective_plan))}</span></td>
            <td style="font-size:12px;color:#555;">${u.created_at ? formatDate(u.created_at) : '—'}</td>
            <td style="font-size:12px;color:#555;">${u.plan_expires_at ? formatDate(u.plan_expires_at) : '—'}</td>
            <td class="col-actions">
              <button class="action-btn detail" data-action="open-user-detail" data-user-id="${escHtml(String(u.id))}">详情</button>
              <button class="action-btn edit" data-action="open-user-edit" data-user-id="${escHtml(String(u.id))}">编辑</button>
              <button class="action-btn delete" data-action="confirm-delete-user" data-user-id="${escHtml(String(u.id))}" data-user-email="${escHtml(String(u.email || ''))}">删除</button>
            </td>
          </tr>
        `).join('')}
      </tbody>
    </table>
    </div>`;

  if (pagerEl) renderPager(pagerEl, page, totalPages, total, (p) => { AdminState.membershipData.usersPage = p; loadMembershipData(); });
}

// ============================================================
// 订单列表渲染
// ============================================================
function renderMembershipOrders() {
  const box = document.getElementById('membership-orders-table-wrap');
  const countLabel = document.getElementById('order-count-label');
  const pagerEl = document.getElementById('order-pager');
  if (!box) return;

  const md = AdminState.membershipData;
  const orders = md.orders;
  const total = md.ordersTotal;
  const page = md.ordersPage;
  const limit = md.ordersLimit;
  const totalPages = Math.ceil(total / limit);

  if (countLabel) countLabel.textContent = `共 ${total} 条订单`;

  if (!orders.length) {
    box.innerHTML = '<div class="no-results">暂无订单数据</div>';
    if (pagerEl) pagerEl.innerHTML = '';
    return;
  }

  const statusLabel = { pending: '待支付', paid: '已支付', expired: '已过期', closed: '已关闭', refunded: '已退款' };
  const statusCls = { pending: 'badge-free', paid: 'badge-vip', expired: 'badge-hidden', closed: 'badge-hidden', refunded: 'badge-svip' };

  box.innerHTML = `
    <div class="table-scroll">
    <table class="order-table">
      <thead>
        <tr>
          <th>订单号</th>
          <th>用户</th>
          <th>档位</th>
          <th>金额</th>
          <th>状态</th>
          <th>创建时间</th>
          <th style="text-align:right">操作</th>
        </tr>
      </thead>
      <tbody>
        ${orders.map(o => `
          <tr>
            <td class="col-no">${escHtml(o.order_no || String(o.id))}</td>
            <td>
              <div style="font-size:13px;">${escHtml(o.user_nickname || o.user_email || '—')}</div>
              <div style="font-size:11px;color:#555;">${escHtml(o.user_email || '')}</div>
            </td>
            <td><span class="badge badge-${o.plan_type || 'free'}">${escHtml(o.plan_label || o.plan_type || 'free')}</span></td>
            <td>${o.amount_cents != null ? `¥${(o.amount_cents / 100).toFixed(2)}` : '—'}</td>
            <td><span class="badge ${statusCls[o.status] || 'badge-free'}">${statusLabel[o.status] || o.status || '未知'}</span></td>
            <td style="font-size:12px;color:#555;">${o.created_at ? formatDate(o.created_at) : '—'}</td>
            <td class="col-actions">
              <button class="action-btn detail" data-action="open-order-detail" data-order-id="${escHtml(String(o.id))}">详情</button>
            </td>
          </tr>
        `).join('')}
      </tbody>
    </table>
    </div>`;

  if (pagerEl) renderPager(pagerEl, page, totalPages, total, (p) => { AdminState.membershipData.ordersPage = p; loadMembershipData(); });
}

// ============================================================
// 用户选择与批量操作
// ============================================================
function toggleUserSelection(userId, checkbox) {
  if (checkbox.checked) {
    AdminState.membershipData.selectedUserIds.add(userId);
  } else {
    AdminState.membershipData.selectedUserIds.delete(userId);
  }
  updateBatchBar();
}

function toggleAllUsers(checkbox) {
  document.querySelectorAll('.user-checkbox[value]').forEach(cb => {
    cb.checked = checkbox.checked;
    const uid = cb.value;
    if (checkbox.checked) AdminState.membershipData.selectedUserIds.add(uid);
    else AdminState.membershipData.selectedUserIds.delete(uid);
  });
  updateBatchBar();
}

function clearUserSelection() {
  AdminState.membershipData.selectedUserIds.clear();
  document.querySelectorAll('.user-checkbox[value]').forEach(cb => { cb.checked = false; });
  const checkAll = document.getElementById('user-check-all');
  if (checkAll) checkAll.checked = false;
  updateBatchBar();
}

function updateBatchBar() {
  const bar = document.getElementById('user-batch-bar');
  const countEl = document.getElementById('user-batch-count');
  const count = AdminState.membershipData.selectedUserIds.size;
  if (!bar) return;
  bar.classList.toggle('active', count > 0);
  if (countEl) countEl.textContent = `已选 ${count} 位用户`;
}

async function batchUpdatePlan() {
  const ids = Array.from(AdminState.membershipData.selectedUserIds);
  if (!ids.length) { toast('请先选择用户'); return; }
  const planType = document.getElementById('batch-plan-select')?.value || 'vip';
  const days = parseInt(document.getElementById('batch-days')?.value) || 30;
  if (!await showConfirm(`确定要将 ${ids.length} 位用户设置为 ${formatPlanLabel(planType)}（${days} 天）？`, '批量操作确认')) return;
  try {
    await AdminAPI.apiFetch(`${AdminAPI.API}/users/batch-plan`, {
      method: 'POST',
      body: JSON.stringify({ user_ids: ids, plan_type: planType, duration_days: days }),
    });
    clearUserSelection();
    toast(`已为 ${ids.length} 位用户设置完成`);
    loadMembershipData();
  } catch (e) {
    toast('批量设置失败：' + e.message);
  }
}

// ============================================================
// 用户详情/编辑弹窗
// ============================================================
async function openUserDetail(userId) {
  const body = document.getElementById('user-detail-body');
  if (!body) return;
  body.innerHTML = '<div class="no-results">加载中…</div>';
  document.getElementById('user-detail-modal').style.display = 'flex';
  // 通过 data 属性传递用户信息给事件委托处理器
  const deleteBtn = document.getElementById('user-detail-delete-btn');
  if (deleteBtn) {
    deleteBtn.dataset.userId = String(userId);
    deleteBtn.dataset.userEmail = '';
  }
  try {
    const u = await AdminAPI.apiFetch(`${AdminAPI.API}/users/${userId}`);
    const deleteBtn = document.getElementById('user-detail-delete-btn');
    if (deleteBtn) deleteBtn.dataset.userEmail = u.email || '';
    body.innerHTML = `
      <div class="detail-grid">
        <div class="dg-item"><div class="dg-label">用户 ID</div><div class="dg-value">#${u.id}</div></div>
        <div class="dg-item"><div class="dg-label">邮箱</div><div class="dg-value">${escHtml(u.email || '—')}</div></div>
        <div class="dg-item"><div class="dg-label">昵称</div><div class="dg-value">${escHtml(u.nickname || '—')}</div></div>
        <div class="dg-item"><div class="dg-label">当前档位</div><div class="dg-value"><span class="badge badge-${u.effective_plan || 'free'}">${escHtml(formatPlanLabel(u.effective_plan))}</span></div></div>
        <div class="dg-item"><div class="dg-label">档位到期</div><div class="dg-value">${u.plan_expires_at ? formatDate(u.plan_expires_at) : '无限制'}</div></div>
        <div class="dg-item"><div class="dg-label">注册时间</div><div class="dg-value">${u.created_at ? formatDate(u.created_at) : '—'}</div></div>
        <div class="dg-item"><div class="dg-label">最后登录</div><div class="dg-value">${u.last_login ? formatDate(u.last_login) : '—'}</div></div>
        <div class="dg-item"><div class="dg-label">对话消息数</div><div class="dg-value">${u.chat_count ?? 0}</div></div>
        <div class="dg-item"><div class="dg-label">关联角色数</div><div class="dg-value">${u.linked_char_count ?? 0}</div></div>
      </div>`;
  } catch (e) {
    body.innerHTML = `<div class="no-results" style="color:#f87171">加载失败：${escHtml(e.message)}</div>`;
  }
}

function closeUserDetailModal() {
  document.getElementById('user-detail-modal').style.display = 'none';
}

function openUserEdit(userId) {
  const u = AdminState.membershipData.users.find(x => x.id === userId);
  if (!u) return;
  document.getElementById('edit-user-id').value = userId;
  document.getElementById('edit-user-email').value = u.email || '';
  document.getElementById('edit-user-nickname').value = u.nickname || '';
  document.getElementById('edit-user-plan').value = u.plan_type || 'free';
  document.getElementById('edit-user-plan-days').value = 30;
  document.getElementById('user-edit-title').textContent = `✏️ 编辑用户 #${userId}`;
  document.getElementById('user-edit-modal').style.display = 'flex';
}

function closeUserEditModal() {
  document.getElementById('user-edit-modal').style.display = 'none';
}

async function saveUserEdit() {
  const userId = document.getElementById('edit-user-id').value;
  const email = document.getElementById('edit-user-email').value.trim();
  const nickname = document.getElementById('edit-user-nickname').value.trim();
  const planType = document.getElementById('edit-user-plan').value;
  const planDays = parseInt(document.getElementById('edit-user-plan-days').value) || 30;
  if (!email) { toast('邮箱不能为空'); return; }
  try {
    // 先保存基本信息
    await AdminAPI.apiFetch(`${AdminAPI.API}/users/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify({ email, nickname }),
    });
    // 再设置会员档位
    await AdminAPI.apiFetch(`${AdminAPI.API}/users/${userId}/plan`, {
      method: 'POST',
      body: JSON.stringify({ plan_type: planType, duration_days: planDays }),
    });
    closeUserEditModal();
    toast('保存成功');
    loadMembershipData();
  } catch (e) {
    toast('保存失败：' + e.message);
  }
}

// ============================================================
// 删除用户
// ============================================================
async function confirmDeleteUser(userId, email) {
  closeUserDetailModal();
  if (!await showConfirm(`确定要删除用户 ${email ? `「${email}」` : `#${userId}`} 吗？\n\n此操作会同时删除该用户的所有聊天记录、角色关系和订单数据，且不可撤销！`, '删除用户确认')) return;
  AdminState.pendingDeleteUserId = userId;
  doDeleteUser();
}

async function doDeleteUser() {
  if (!AdminState.pendingDeleteUserId) return;
  const userId = AdminState.pendingDeleteUserId;
  AdminState.pendingDeleteUserId = null;
  try {
    await AdminAPI.apiFetch(`${AdminAPI.API}/users/${userId}`, { method: 'DELETE' });
    toast('用户已删除');
    loadMembershipData();
  } catch (e) {
    toast('删除失败：' + e.message);
  }
}

// ============================================================
// 订单详情
// ============================================================
async function openOrderDetail(orderId) {
  const body = document.getElementById('order-detail-body');
  if (!body) return;
  body.innerHTML = '<div class="no-results">加载中…</div>';
  document.getElementById('order-detail-modal').style.display = 'flex';
  try {
    const o = await AdminAPI.apiFetch(`${AdminAPI.API}/orders/${orderId}`);
    const statusLabel = { pending: '待支付', paid: '已支付', expired: '已过期', closed: '已关闭', refunded: '已退款' };
    body.innerHTML = `
      <div class="detail-grid">
        <div class="dg-item"><div class="dg-label">订单 ID</div><div class="dg-value">#${o.id}</div></div>
        <div class="dg-item"><div class="dg-label">订单号</div><div class="dg-value" style="font-family:monospace;font-size:12px;">${escHtml(o.order_no || '—')}</div></div>
        <div class="dg-item"><div class="dg-label">用户</div><div class="dg-value">${escHtml(o.user_nickname || o.user_email || '—')}<br><span style="color:#555;font-size:12px;">${escHtml(o.user_email || '')}</span></div></div>
        <div class="dg-item"><div class="dg-label">档位</div><div class="dg-value"><span class="badge badge-${o.plan_type || 'free'}">${escHtml(o.plan_label || o.plan_type || 'free')}</span></div></div>
        <div class="dg-item"><div class="dg-label">金额</div><div class="dg-value">${o.amount_cents != null ? `¥${(o.amount_cents / 100).toFixed(2)}` : '—'}</div></div>
        <div class="dg-item"><div class="dg-label">时长</div><div class="dg-value">${o.duration_days ? `${o.duration_days} 天` : '—'}</div></div>
        <div class="dg-item"><div class="dg-label">状态</div><div class="dg-value"><span class="badge badge-${o.status}">${statusLabel[o.status] || o.status || '未知'}</span></div></div>
        <div class="dg-item"><div class="dg-label">支付渠道</div><div class="dg-value">${escHtml(o.payment_provider || '—')}</div></div>
        <div class="dg-item dg-full"><div class="dg-label">渠道订单号</div><div class="dg-value" style="font-family:monospace;font-size:12px;">${escHtml(o.provider_trade_no || '—')}</div></div>
        <div class="dg-item dg-full"><div class="dg-label">支付链接</div><div class="dg-value" style="font-size:12px;"><a href="${escHtml(o.checkout_url || '#')}" target="_blank" style="color:#60a5fa;word-break:break-all;">${escHtml(o.checkout_url || '—')}</a></div></div>
        <div class="dg-item"><div class="dg-label">创建时间</div><div class="dg-value">${o.created_at ? formatDate(o.created_at) : '—'}</div></div>
        <div class="dg-item"><div class="dg-label">支付时间</div><div class="dg-value">${o.paid_at ? formatDate(o.paid_at) : '—'}</div></div>
        <div class="dg-item"><div class="dg-label">到期时间</div><div class="dg-value">${o.expires_at ? formatDate(o.expires_at) : '—'}</div></div>
        <div class="dg-item"><div class="dg-label">关闭时间</div><div class="dg-value">${o.closed_at ? formatDate(o.closed_at) : '—'}</div></div>
      </div>`;
  } catch (e) {
    body.innerHTML = `<div class="no-results" style="color:#f87171">加载失败：${escHtml(e.message)}</div>`;
  }
}

function closeOrderDetailModal() {
  document.getElementById('order-detail-modal').style.display = 'none';
}

// ============================================================
// CSV 导出
// ============================================================
async function exportUsersCSV() {
  try {
    toast('正在生成 CSV…');
    const users = await AdminAPI.apiFetch(`${AdminAPI.API}/users/export`);
    const rows = [['ID', '邮箱', '昵称', '档位', '到期时间', '注册时间', '对话数', '关联角色数']];
    users.forEach(u => {
      rows.push([
        u.id, u.email || '', u.nickname || '',
        u.effective_plan || 'free', u.plan_expires_at || '',
        u.created_at || '', u.chat_count || 0, u.linked_char_count || 0,
      ]);
    });
    downloadCSV('users_export.csv', rows);
    toast('CSV 已下载');
  } catch (e) {
    toast('导出失败：' + e.message);
  }
}

async function exportOrdersCSV() {
  try {
    toast('正在生成 CSV…');
    const orders = await AdminAPI.apiFetch(`${AdminAPI.API}/orders/export`);
    const rows = [['ID', '订单号', '用户邮箱', '昵称', '档位', '金额', '状态', '渠道', '渠道单号', '创建时间', '支付时间', '到期时间']];
    orders.forEach(o => {
      rows.push([
        o.id, o.order_no || '', o.user_email || '', o.user_nickname || '',
        o.plan_type || '', o.amount_cents != null ? (o.amount_cents / 100).toFixed(2) : '',
        o.status || '', o.payment_provider || '', o.provider_trade_no || '',
        o.created_at || '', o.paid_at || '', o.expires_at || '',
      ]);
    });
    downloadCSV('orders_export.csv', rows);
    toast('CSV 已下载');
  } catch (e) {
    toast('导出失败：' + e.message);
  }
}
