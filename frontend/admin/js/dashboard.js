/**
 * dashboard.js - 仪表盘标签页逻辑
 *
 * 包含：统计卡片、趋势图、会员分布。
 * 依赖：utils.js, api.js
 */

async function loadDashboard() {
  const box = document.getElementById('dashboard-content');
  if (!box) return;
  box.innerHTML = skeletonHtml(2, 4);
  try {
    const [stats, trend, mediaMissing, configHealth] = await Promise.all([
      AdminAPI.apiFetch(`${AdminAPI.API}/dashboard/stats`),
      AdminAPI.apiFetch(`${AdminAPI.API}/dashboard/trend?days=7`),
      AdminAPI.apiFetch(`${AdminAPI.API}/media-missing`).catch(() => ({
        ok: false,
        missing_count: 0,
        items: [],
        truncated: false,
      })),
      AdminAPI.apiFetch(`${AdminAPI.API}/config-health`).catch(() => ({
        ok: false,
        summary: { ready_count: 0, warning_count: 0, error_count: 1 },
        items: [{
          key: 'config_health',
          label: '配置健康',
          status: 'error',
          value: '检查失败',
          hint: '无法读取配置健康状态，请检查后台服务。',
        }],
      })),
    ]);
    renderDashboard(stats, trend, mediaMissing, configHealth);
  } catch (e) {
    box.innerHTML = `<div class="no-results" style="color:#f87171">加载失败：${escHtml(e.message)}</div>`;
  }
}

function renderDashboard(stats, trend, mediaMissing = {}, configHealth = {}) {
  const box = document.getElementById('dashboard-content');
  if (!box) return;
  const configHealthClasses = new Set(['ready', 'warning', 'error']);
  const dist = stats.plan_distribution || {};
  const trendData = trend.trend || [];
  const maxUsers = Math.max(...trendData.map(t => t.new_users), 1);
  const maxOrders = Math.max(...trendData.map(t => t.new_orders), 1);
  const maxRevenue = Math.max(...trendData.map(t => t.revenue), 1);
  const missingCount = Number(mediaMissing.missing_count || 0);
  const missingItems = Array.isArray(mediaMissing.items) ? mediaMissing.items : [];
  const mediaHealthy = Boolean(mediaMissing.ok) && missingCount === 0;
  const mediaStatusClass = mediaHealthy ? 'ok' : 'warn';
  const mediaStatusText = mediaHealthy ? '媒体资源完整' : `发现 ${missingCount} 个缺失资源`;
  const mediaListHtml = missingItems.length > 0
    ? `<ul class="media-missing-list">${missingItems.map(item => `<li>${escHtml(item)}</li>`).join('')}</ul>`
    : '<div class="media-missing-empty">暂无缺失样例</div>';
  const truncatedHint = mediaMissing.truncated
    ? '<div class="media-missing-hint">仅展示样例，请点击“刷新缺失清单”获取最新结果。</div>'
    : '';
  const configItems = Array.isArray(configHealth.items) ? configHealth.items : [];
  const configSummary = configHealth.summary || {};
  const configStatusClass = configHealth.ok ? 'ok' : (Number(configSummary.error_count || 0) > 0 ? 'error' : 'warn');
  const configStatusText = configHealth.ok
    ? '关键配置正常'
    : `正常 ${configSummary.ready_count || 0} 项，警告 ${configSummary.warning_count || 0} 项，错误 ${configSummary.error_count || 0} 项`;
  const configHealthHtml = configItems.length > 0
    ? configItems.map(item => {
      const itemStatus = configHealthClasses.has(item.status) ? item.status : 'warning';
      return `
        <div class="config-health-item ${itemStatus}">
          <div class="config-health-main">
            <span class="config-health-label">${escHtml(item.label || item.key || '')}</span>
            <span class="config-health-value">${escHtml(item.value || '')}</span>
          </div>
          <div class="config-health-hint">${escHtml(item.hint || '')}</div>
        </div>
      `;
    }).join('')
    : '<div class="media-missing-empty">暂无配置健康数据</div>';

  const storage = stats.storage || {};
  const usedPercent = Number(storage.used_percent || 0);
  let storageClass = 'safe';
  if (usedPercent >= 90) storageClass = 'critical';
  else if (usedPercent >= 80) storageClass = 'danger';
  else if (usedPercent >= 60) storageClass = 'warn';
  const storageBarWidth = Math.min(usedPercent, 100);

  box.innerHTML = `
    <div class="dashboard-grid">
      <div class="stat-card purple clickable" data-action="switch-system-tab" data-tab="membership" title="点击查看用户管理">
        <div class="stat-icon">👥</div>
        <div class="stat-value">${stats.total_users ?? 0}</div>
        <div class="stat-label">总用户数</div>
        <div class="stat-sub">今日 +${stats.today_new_users ?? 0}</div>
      </div>
      <div class="stat-card green clickable" data-action="switch-system-tab" data-tab="membership" title="点击查看会员管理">
        <div class="stat-icon">💰</div>
        <div class="stat-value">${stats.paid_users ?? 0}</div>
        <div class="stat-label">付费用户</div>
        <div class="stat-sub">付费率 ${stats.paid_rate ?? 0}%</div>
      </div>
      <div class="stat-card blue clickable" data-action="switch-system-tab" data-tab="membership" data-scroll="orders" title="点击查看订单管理">
        <div class="stat-icon">📦</div>
        <div class="stat-value">${stats.today_orders ?? 0}</div>
        <div class="stat-label">今日订单</div>
        <div class="stat-sub">¥${((stats.today_revenue || 0) / 100).toFixed(2)} 今日收入</div>
      </div>
      <div class="stat-card yellow clickable" data-action="switch-system-tab" data-tab="membership" title="即将到期的用户">
        <div class="stat-icon">⏰</div>
        <div class="stat-value">${stats.expiring_soon ?? 0}</div>
        <div class="stat-label">即将到期</div>
        <div class="stat-sub">3 天内</div>
      </div>
    </div>

    <div class="storage-usage-card">
      <div class="storage-header">
        <span>🗄️ 数据库存储</span>
        <span class="storage-value">${storage.size_mb ?? '--'} MB / ${storage.limit_mb ?? 500} MB</span>
      </div>
      <div class="storage-bar-bg">
        <div class="storage-bar-fill ${storageClass}" style="width:${storageBarWidth}%"></div>
      </div>
      <div class="storage-footer">已使用 ${usedPercent}%${usedPercent >= 80 ? ' ⚠️ 请关注扩容' : ''}</div>
    </div>

    <div class="dashboard-section config-health-section">
      <div class="media-missing-header">
        <h3>🧭 配置健康</h3>
      </div>
      <div class="config-health-status ${configStatusClass}">${configStatusText}</div>
      <div class="config-health-list">${configHealthHtml}</div>
    </div>

    <div class="dashboard-section">
      <h3>📈 近 7 天趋势</h3>
      <div class="trend-metrics">
        <div class="trend-metric">
          <div class="trend-metric-label">👤 新增用户</div>
          <div class="trend-chart">
            ${trendData.map(t => `
              <div class="trend-bar-wrap">
                <div class="trend-value">${t.new_users}</div>
                <div class="trend-bar" style="height:${Math.max(4, Math.round((t.new_users / maxUsers) * 60))}px"></div>
                <div class="trend-label">${(t.date || '').slice(5)}</div>
              </div>
            `).join('')}
          </div>
        </div>
        <div class="trend-metric">
          <div class="trend-metric-label">📦 新增订单</div>
          <div class="trend-chart">
            ${trendData.map(t => `
              <div class="trend-bar-wrap">
                <div class="trend-value">${t.new_orders}</div>
                <div class="trend-bar trend-bar-green" style="height:${Math.max(4, Math.round((t.new_orders / maxOrders) * 60))}px"></div>
                <div class="trend-label">${(t.date || '').slice(5)}</div>
              </div>
            `).join('')}
          </div>
        </div>
        <div class="trend-metric">
          <div class="trend-metric-label">💰 收入(元)</div>
          <div class="trend-chart">
            ${trendData.map(t => `
              <div class="trend-bar-wrap">
                <div class="trend-value">${(t.revenue / 100).toFixed(0)}</div>
                <div class="trend-bar trend-bar-yellow" style="height:${Math.max(4, Math.round((t.revenue / maxRevenue) * 60))}px"></div>
                <div class="trend-label">${(t.date || '').slice(5)}</div>
              </div>
            `).join('')}
          </div>
        </div>
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
    </div>

    <div class="dashboard-section media-missing-section">
      <div class="media-missing-header">
        <h3>🧩 媒体缺失告警</h3>
        <button class="btn btn-ghost" data-action="load-media-missing" data-refresh="true">🔄 刷新缺失清单</button>
      </div>
      <div class="media-missing-status ${mediaStatusClass}">${mediaStatusText}</div>
      <div id="media-missing-panel">${mediaListHtml}${truncatedHint}</div>
    </div>`;
}

async function loadMediaMissing(forceRefresh = true) {
  const panel = document.getElementById('media-missing-panel');
  const status = document.querySelector('.media-missing-status');
  if (!panel || !status) return;

  panel.innerHTML = '<div class="no-results">加载中…</div>';
  try {
    const query = forceRefresh ? '?refresh=true' : '';
    const mediaMissing = await AdminAPI.apiFetch(`${AdminAPI.API}/media-missing${query}`);
    const missingCount = Number(mediaMissing.missing_count || 0);
    const missingItems = Array.isArray(mediaMissing.items) ? mediaMissing.items : [];
    const mediaHealthy = Boolean(mediaMissing.ok) && missingCount === 0;
    status.classList.remove('ok', 'warn');
    status.classList.add(mediaHealthy ? 'ok' : 'warn');
    status.textContent = mediaHealthy ? '媒体资源完整' : `发现 ${missingCount} 个缺失资源`;

    const listHtml = missingItems.length > 0
      ? `<ul class="media-missing-list">${missingItems.map(item => `<li>${escHtml(item)}</li>`).join('')}</ul>`
      : '<div class="media-missing-empty">暂无缺失样例</div>';
    const truncatedHint = mediaMissing.truncated
      ? '<div class="media-missing-hint">仅展示样例，请继续排查数据库中的历史路径。</div>'
      : '';
    panel.innerHTML = `${listHtml}${truncatedHint}`;
  } catch (e) {
    status.classList.remove('ok');
    status.classList.add('warn');
    status.textContent = '媒体缺失清单加载失败';
    panel.innerHTML = `<div class="no-results" style="color:#f87171">加载失败：${escHtml(e.message)}</div>`;
  }
}
