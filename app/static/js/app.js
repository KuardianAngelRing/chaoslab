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
function openDialog(name) {
  const d = document.getElementById(`dialog-${name}`);
  if (!d) return;
  d.classList.add('open');
  const card = d.querySelector('[data-wizard]');
  if (card) { wizReset(card); applyDialogWidth(card); }  // 열 때마다 step1 리셋 + 저장 너비 재적용
}
function closeDialog(name) { const d = document.getElementById(`dialog-${name}`); if (d) d.classList.remove('open'); }
document.addEventListener('click', (e) => {
  if (e.target.classList && e.target.classList.contains('dialog-backdrop')) e.target.classList.remove('open');
});

// ── 등록 모달: 3-step 위저드 (클라이언트 show/hide, submit은 마지막 1회) ──
const WIZ_STEPS = 3;
function wizRender(card) {
  const step = +(card.dataset.wizStep || 1);
  card.querySelectorAll('[data-wiz-panel]').forEach((p) =>
    p.classList.toggle('hidden', +p.dataset.wizPanel !== step));
  card.querySelectorAll('[data-wiz-dot]').forEach((dot) => {
    const on = +dot.dataset.wizDot <= step;  // 현재·완료 스텝 강조
    const c = dot.querySelector('[data-wiz-circle]');
    c.style.background = on ? 'var(--primary)' : 'var(--muted)';
    c.style.color = on ? 'var(--primary-foreground)' : 'var(--muted-foreground)';
  });
  const prev = card.querySelector('[data-wiz-prev]');
  const next = card.querySelector('[data-wiz-next]');
  const submit = card.querySelector('[data-wiz-submit]');
  if (prev) prev.classList.toggle('invisible', step === 1);
  if (next) next.classList.toggle('hidden', step === WIZ_STEPS);
  if (submit) submit.classList.toggle('hidden', step !== WIZ_STEPS);
}
function wizReset(card) { card.dataset.wizStep = '1'; wizRender(card); }
function wizGo(card, dir) {
  let step = +(card.dataset.wizStep || 1);
  if (dir > 0) {  // 다음 누를 때 현재 패널 필수값 검증
    const panel = card.querySelector(`[data-wiz-panel="${step}"]`);
    const bad = [...panel.querySelectorAll('[data-wiz-required]')].find((i) => !i.value.trim());
    if (bad) { bad.reportValidity ? bad.reportValidity() : bad.focus(); return; }
  }
  card.dataset.wizStep = String(Math.min(WIZ_STEPS, Math.max(1, step + dir)));
  wizRender(card);
}
document.addEventListener('click', (e) => {
  const next = e.target.closest('[data-wiz-next]');
  const prev = e.target.closest('[data-wiz-prev]');
  if (next) wizGo(next.closest('[data-wizard]'), +1);
  else if (prev) wizGo(prev.closest('[data-wizard]'), -1);
});

// ── 모달 우측 가장자리 드래그 리사이즈 ──
// 너비는 모듈 변수에 보관 → HTMX 스왑 간에는 유지, 풀 리프레시 시 초기화.
let _dialogWidth = null;
function applyDialogWidth(card) {
  if (_dialogWidth && card) { card.style.maxWidth = 'none'; card.style.width = `${_dialogWidth}px`; }
}
document.addEventListener('mousedown', (e) => {
  const handle = e.target.closest('.dialog-resize-handle');
  if (!handle) return;
  e.preventDefault();
  const card = handle.closest('.dialog-card');
  const startX = e.clientX;
  const startW = card.offsetWidth;
  card.style.maxWidth = 'none';
  document.body.style.userSelect = 'none';
  const onMove = (ev) => {
    // flex-center 보정: 카드가 양쪽으로 커지므로 delta를 2배 적용해 핸들이 커서를 따라오게
    const w = Math.round(startW + 2 * (ev.clientX - startX));
    _dialogWidth = Math.max(360, Math.min(window.innerWidth - 32, w));
    card.style.width = `${_dialogWidth}px`;
  };
  const onUp = () => {
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    document.body.style.userSelect = '';
  };
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
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
  if (rIdx && rIdx.dataset.series) {
    const data = JSON.parse(rIdx.dataset.series);
    const labels = JSON.parse(rIdx.dataset.labels || '[]');
    if (data.length) {
      window._charts.rIndex = new Chart(rIdx, {
        type: 'line',
        data: { labels, datasets: [{ data, borderColor: '#004b3e', backgroundColor: 'rgba(0,75,62,0.15)', fill: true, tension: 0.3, pointRadius: 5, pointBackgroundColor: '#004b3e', borderWidth: 3 }] },
        options: { ...cc, scales: { ...cc.scales, y: { ...cc.scales.y, min: 0.3, max: 0.8 } } }
      });
    }
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

// ── 등록 폼 env/secret 에디터 (vanilla, HTMX 스왑 안전: 위임 + onclick 전역) ──
const ENV_SECRET_RE = /(TOKEN|SECRET|PASSWORD|KEY)/i;

function escapeAttr(s) { return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;'); }

function envRowHtml(key = '', value = '', secret = false) {
  return `<div class="env-row flex items-center gap-2">
    <input class="env-key tds-input mono text-xs" placeholder="KEY" value="${escapeAttr(key)}" />
    <input class="env-val tds-input mono text-xs" placeholder="value" value="${escapeAttr(value)}" />
    <label class="flex items-center gap-1 text-xs whitespace-nowrap" title="시크릿">
      <input type="checkbox" class="env-secret" ${secret ? 'checked' : ''} />🔒
    </label>
    <button type="button" class="tds-btn-muted text-xs px-2" onclick="this.closest('.env-row').remove(); envSync()">✕</button>
  </div>`;
}

function envAddRow(key = '', value = '', secret = false) {
  const box = document.getElementById('env-rows');
  if (!box) return;
  box.insertAdjacentHTML('beforeend', envRowHtml(key, value, secret));
  envSync();
}

function envParsePaste() {
  const ta = document.getElementById('env-paste');
  if (!ta) return;
  ta.value.split('\n').forEach((line) => {
    const i = line.indexOf('=');
    if (i < 1) return;
    const key = line.slice(0, i).trim();
    const val = line.slice(i + 1).trim();
    if (key) envAddRow(key, val, ENV_SECRET_RE.test(key));
  });
  ta.value = '';
}

function envSync() {
  const json = document.getElementById('env-json');
  if (!json) return;
  const rows = [...document.querySelectorAll('#env-rows .env-row')].map((r) => ({
    key: r.querySelector('.env-key').value.trim(),
    value: r.querySelector('.env-val').value,
    is_secret: r.querySelector('.env-secret').checked,
  })).filter((e) => e.key);
  json.value = JSON.stringify(rows);
}

// 행 입력 시마다 hidden 동기화 + 키 입력 시 시크릿 자동 감지(미수정 시)
document.addEventListener('input', (e) => {
  if (!e.target.closest('#env-rows')) return;
  if (e.target.classList.contains('env-key')) {
    const row = e.target.closest('.env-row');
    const cb = row.querySelector('.env-secret');
    if (!cb.dataset.touched) cb.checked = ENV_SECRET_RE.test(e.target.value);
  }
  envSync();
});
document.addEventListener('change', (e) => {
  if (e.target.classList && e.target.classList.contains('env-secret')) {
    e.target.dataset.touched = '1';  // 수동 토글 후엔 자동감지 중단
    envSync();
  }
});

// ── 빌드 상태 watch (building 카드만 EventSource, 완료 시 목록 새로고침) ──
const _buildStreams = new Set();
function watchBuilds() {
  document.querySelectorAll('[data-building-app]').forEach((el) => {
    const id = el.dataset.buildingApp;
    if (_buildStreams.has(id)) return;
    _buildStreams.add(id);
    const es = new EventSource(`/apps/${id}/builds/stream`);
    es.addEventListener('completed', () => {
      es.close(); _buildStreams.delete(id);
      // 배지 마크업을 JS에 복제하지 않고 서버 렌더로 목록 새로고침(배지·sha 일관)
      if (window.htmx) htmx.ajax('GET', '/apps', { target: '#main-content', swap: 'innerHTML' });
    });
    es.onerror = () => { es.close(); _buildStreams.delete(id); };
  });
}
document.addEventListener('DOMContentLoaded', watchBuilds);
document.body.addEventListener('htmx:afterSwap', watchBuilds);

// ── 사이드바 active 동기화 (HTMX 부분 스왑은 사이드바 DOM을 안 바꿈) ──
function syncSidebarActive() {
  const path = location.pathname;
  document.querySelectorAll('.sidebar-nav-item').forEach((a) => {
    const href = a.getAttribute('hx-get');
    // 루트는 정확히, 나머지는 하위경로(/experiments/3 등)까지 매칭 — 서버 active_nav와 동일
    const match = href === '/' ? path === '/' : path === href || path.startsWith(href + '/');
    a.classList.toggle('active', match);
  });
}
document.addEventListener('DOMContentLoaded', syncSidebarActive);
document.body.addEventListener('htmx:afterSwap', syncSidebarActive);
document.body.addEventListener('htmx:historyRestore', syncSidebarActive);
