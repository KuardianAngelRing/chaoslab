// ============== 유저 메뉴 ==============
document.addEventListener('click', (e) => {
  const btn = document.getElementById('userMenuBtn');
  const menu = document.getElementById('userMenu');
  if (!menu) return;
  if (btn && btn.contains(e.target)) { e.stopPropagation(); menu.classList.toggle('open'); return; }
  if (!menu.contains(e.target)) menu.classList.remove('open');
});

// ============== 테마 토글 ==============
document.addEventListener('click', (e) => {
  const t = e.target.closest && e.target.closest('#themeToggleBtn');
  if (!t) return;
  e.stopPropagation();
  const cur = document.documentElement.getAttribute('data-theme');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  const icon = document.getElementById('themeIcon');
  const label = document.getElementById('themeLabel');
  if (icon) icon.setAttribute('icon', next === 'dark' ? 'solar:sun-bold' : 'solar:moon-bold');
  if (label) label.textContent = next === 'dark' ? '라이트 모드' : '다크 모드';
  Object.values(window._charts || {}).forEach(c => c && c.update());
});

// ============== 탭 전환 (이벤트 위임) ==============
document.addEventListener('click', (e) => {
  const t = e.target.closest && e.target.closest('[data-tab-trigger]');
  if (!t) return;
  const group = t.dataset.tabGroup;
  const target = t.dataset.tabTrigger;
  document.querySelectorAll(`[data-tab-trigger][data-tab-group="${group}"]`).forEach(el => el.classList.remove('active'));
  t.classList.add('active');
  document.querySelectorAll(`[data-tab-content][data-tab-group="${group}"]`).forEach(el => el.classList.remove('active'));
  const content = document.querySelector(`[data-tab-content="${target}"][data-tab-group="${group}"]`);
  if (content) content.classList.add('active');
});

// ============== 다이얼로그 ==============
function openDialog(name) { const d = document.getElementById(`dialog-${name}`); if (d) d.classList.add('open'); }
function closeDialog(name) { const d = document.getElementById(`dialog-${name}`); if (d) d.classList.remove('open'); }
document.addEventListener('click', (e) => {
  if (e.target.classList && e.target.classList.contains('dialog-backdrop')) e.target.classList.remove('open');
});

// ============== Chart.js ==============
const tdsTextColor = () => getComputedStyle(document.documentElement).getPropertyValue('--muted-foreground').trim();
const tdsBorderColor = () => getComputedStyle(document.documentElement).getPropertyValue('--border').trim();

function chartCommon() {
  return {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { display: false }, ticks: { color: tdsTextColor(), font: { size: 10 } } },
      y: { grid: { color: tdsBorderColor() }, ticks: { color: tdsTextColor(), font: { size: 10 } } }
    }
  };
}

function makeTimeSeries(canvasId, color, base, variance, isStep = false) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  const labels = Array.from({ length: 30 }, (_, i) => `${30 - i}m`).reverse();
  const data = labels.map((_, i) => {
    if (i < 5) return base * 0.3;
    if (i < 18) return base + (Math.random() - 0.5) * variance;
    return base * 0.4 + (Math.random() - 0.5) * (variance * 0.3);
  });
  const cc = chartCommon();
  window._charts[canvasId] = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [{ data, borderColor: color, backgroundColor: color + '22', fill: true, tension: isStep ? 0 : 0.4, stepped: isStep, pointRadius: 0, borderWidth: 2 }] },
    options: { ...cc, scales: { ...cc.scales, x: { display: false } } }
  });
}

function initCharts() {
  // 기존 차트 파기 (HTMX 재스왑 대비)
  Object.values(window._charts || {}).forEach(c => c && c.destroy());
  window._charts = {};
  const cc = chartCommon();

  const rIdx = document.getElementById('rIndexChart');
  if (rIdx) {
    window._charts.rIndex = new Chart(rIdx, {
      type: 'line',
      data: { labels: ['iter 1', 'iter 2', 'iter 3', 'iter 4'], datasets: [{ data: [0.42, 0.51, 0.59, 0.65], borderColor: '#004b3e', backgroundColor: 'rgba(0,75,62,0.15)', fill: true, tension: 0.3, pointRadius: 5, pointBackgroundColor: '#004b3e', borderWidth: 3 }] },
      options: { ...cc, scales: { ...cc.scales, y: { ...cc.scales.y, min: 0.3, max: 0.8 } } }
    });
  }

  const agentR = document.getElementById('agentRChart2');
  if (agentR) {
    window._charts.agentR2 = new Chart(agentR, {
      type: 'line',
      data: { labels: ['iter 1', 'iter 2', 'iter 3', 'iter 4', 'iter 5', 'iter 6', 'iter 7'], datasets: [
        { label: '실측', data: [0.42, 0.51, 0.59, 0.65, null, null, null], borderColor: '#004b3e', backgroundColor: 'rgba(0,75,62,0.2)', fill: true, tension: 0.3, pointRadius: 6, pointBackgroundColor: '#004b3e', borderWidth: 3 },
        { label: '예측', data: [null, null, null, 0.65, 0.69, 0.71, 0.73], borderColor: '#0d9488', borderDash: [6, 6], tension: 0.3, pointRadius: 4, borderWidth: 2 },
        { label: '목표', data: [0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7], borderColor: '#dc2626', borderDash: [3, 3], tension: 0, pointRadius: 0, borderWidth: 1.5 }
      ] },
      options: { ...cc, plugins: { legend: { display: true, position: 'bottom', labels: { font: { size: 10 }, color: tdsTextColor() } } }, scales: { ...cc.scales, y: { ...cc.scales.y, min: 0.3, max: 0.85 } } }
    });
  }

  makeTimeSeries('metricRate2', '#004b3e', 42, 8);
  makeTimeSeries('metricError2', '#dc2626', 1.8, 1.5);
  makeTimeSeries('metricLatency2', '#f59e0b', 380, 80);

  const pods = document.getElementById('metricPods2');
  if (pods) {
    const labels = Array.from({ length: 30 }, (_, i) => `${30 - i}m`).reverse();
    window._charts.pods2 = new Chart(pods, {
      type: 'line',
      data: { labels, datasets: [{ data: labels.map(() => 2), borderColor: '#16a34a', backgroundColor: 'rgba(22,163,74,0.15)', fill: true, stepped: true, pointRadius: 0, borderWidth: 2 }] },
      options: { ...cc, scales: { ...cc.scales, x: { display: false }, y: { ...cc.scales.y, min: 0, max: 3 } } }
    });
  }
}

window._charts = {};
document.addEventListener('DOMContentLoaded', initCharts);
document.body.addEventListener('htmx:afterSwap', initCharts);
