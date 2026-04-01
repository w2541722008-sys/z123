/**
 * dashboard.js - 仪表盘标签页逻辑
 *
 * 包含：统计卡片、趋势图、会员分布。
 * 依赖：utils.js, api.js
 */

async function loadDashboard() {
  const box = document.getElementById('dashboard-content');
  if (!box) return;
  box.innerHTML = '<div class="no-results">加载中…</div>';
  try {
    const [stats, trend] = await Promise.all([
      AdminAPI.apiFetch(`${AdminAPI.API}/dashboard/stats`),
      AdminAPI.apiFetch(`${AdminAPI.API}/dashboard/trend?days=7`),
    ]);
    renderDashboard(stats, trend);
  } catch (e) {
    box.innerHTML = `<div class="no-results" style="color:#f87171">加载失败：${escHtml(e.message)}</div>`;
  }
}

function renderDashboard(stats, trend) {
  const box = document.getElementById('dashboard-content');
  if (!box) return;
  const dist = stats.plan_distribution || {};
  const maxUsers = Math.max(...(trend.trend || []).map(t => t.new_users), 1);

  box.innerHTML = `
    <div class="dashboard-grid">
      <div class="stat-card purple">
        <div class="stat-icon">👥</div>
        <div class="stat-value">${stats.total_users ?? 0}</div>
        <div class="stat-label">总用户数</div>
        <div class="stat-sub">今日 +${stats.today_new_users ?? 0}</div>
      </div>
      <div class="stat-card green">
        <div class="stat-icon">💰</div>
        <div class="stat-value">${stats.paid_users ?? 0}</div>
        <div class="stat-label">付费用户</div>
        <div class="stat-sub">付费率 ${stats.paid_rate ?? 0}%</div>
      </div>
      <div class="stat-card blue">
        <div class="stat-icon">📦</div>
        <div class="stat-value">${stats.today_orders ?? 0}</div>
        <div class="stat-label">今日订单</div>
        <div class="stat-sub">¥${((stats.today_revenue || 0) / 100).toFixed(2)} 今日收入</div>
      </div>
      <div class="stat-card yellow">
        <div class="stat-icon">⏰</div>
        <div class="stat-value">${stats.expiring_soon ?? 0}</div>
        <div class="stat-label">即将到期</div>
        <div class="stat-sub">3 天内</div>
      </div>
    </div>

    <div class="dashboard-section">
      <h3>📈 近 7 天趋势</h3>
      <div class="trend-chart">
        ${(trend.trend || []).map(t => `
          <div class="trend-bar-wrap">
            <div class="trend-value">${t.new_users}</div>
            <div class="trend-bar" style="height:${Math.max(4, Math.round((t.new_users / maxUsers) * 80))}px"></div>
            <div class="trend-label">${(t.date || '').slice(5)}</div>
          </div>
        `).join('')}
      </div>
    </div>

    <div class="dashboard-section">
      <h3>👥 会员分布</h3>
      <div class="plan-dist">
        <div class="plan-dist-item">
          <div class="pd-value" style="color:#93c5fd">${dist.free || 0}</div>
          <div class="pd-label">Free</div>
        </div>
        <div class="plan-dist-item">
          <div class="pd-value" style="color:#fbbf24">${dist.vip || 0}</div>
          <div class="pd-label">VIP</div>
        </div>
        <div class="plan-dist-item">
          <div class="pd-value" style="color:#f0abfc">${dist.svip || 0}</div>
          <div class="pd-label">SVIP</div>
        </div>
        <div class="plan-dist-item">
          <div class="pd-value" style="color:#4ade80">${(stats.avg_order_value || 0) / 100}</div>
          <div class="pd-label">均客单价(¥)</div>
        </div>
      </div>
    </div>`;
}
