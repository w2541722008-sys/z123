/**
 * audit-log.js - 操作日志标签页逻辑
 *
 * 包含：日志列表渲染、分页、筛选。
 * 依赖：utils.js, api.js, state.js
 */

async function loadAuditLogs() {
  const box = document.getElementById('audit-logs-table-wrap');
  const pagerEl = document.getElementById('audit-pager');
  const countLabel = document.getElementById('audit-count-label');
  if (!box) return;
  box.innerHTML = skeletonHtml(0, 4);

  const action = document.getElementById('audit-action-filter')?.value || '';
  const dateFrom = document.getElementById('audit-date-from')?.value || '';
  const dateTo = document.getElementById('audit-date-to')?.value || '';
  try {
    const params = new URLSearchParams({ page: String(AdminState.auditPage), limit: '50' });
    if (action) params.set('action', action);
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    const res = await AdminAPI.apiFetch(`${AdminAPI.API}/audit-logs?${params.toString()}`);
    const logs = res.logs || [];
    const total = res.total || 0;
    const totalPages = Math.ceil(total / 50);
    if (countLabel) countLabel.textContent = `共 ${total} 条记录`;

    if (!logs.length) {
      box.innerHTML = '<div class="no-results">暂无操作日志</div>';
      if (pagerEl) pagerEl.innerHTML = '';
      return;
    }

    const actionTag = {
      delete_user: ['delete', '删除用户'],
      edit_user: ['edit', '编辑用户'],
      update_user_plan: ['edit', '修改档位'],
      batch_update: ['batch', '批量操作'],
      create_character: ['create', '创建角色'],
      update_character: ['edit', '更新角色'],
      delete_character: ['delete', '删除角色'],
      delete_storyline: ['delete', '删除剧情线'],
    };

    box.innerHTML = `
      <table class="audit-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>操作人</th>
            <th>操作类型</th>
            <th>对象类型</th>
            <th>对象ID</th>
            <th>详情</th>
          </tr>
        </thead>
        <tbody>
          ${logs.map(l => {
            const [cls, label] = actionTag[l.action] || ['', l.action || ''];
            const detail = l.detail ? Object.entries(l.detail).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(', ') : '';
            return `
              <tr>
                <td class="col-time">${l.created_at ? formatDate(l.created_at) : '—'}</td>
                <td style="font-size:12px;color:#888;">${escHtml(l.operator_email || String(l.operator_id))}</td>
                <td class="col-action"><span class="action-tag ${cls}">${label}</span></td>
                <td style="font-size:12px;color:#888;">${escHtml(l.target_type || '—')}</td>
                <td class="col-id">${escHtml(l.target_id || '—')}</td>
                <td style="font-size:11px;color:#555;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escHtml(detail)}">${escHtml(detail || '—')}</td>
              </tr>`;
          }).join('')}
        </tbody>
      </table>`;

    if (pagerEl) renderPager(pagerEl, AdminState.auditPage, totalPages, total, (p) => { AdminState.auditPage = p; loadAuditLogs(); });
  } catch (e) {
    box.innerHTML = `<div class="no-results" style="color:#f87171">加载失败：${escHtml(e.message)}</div>`;
  }
}
