// ============== 카드 ... 드롭다운 메뉴 (이벤트 위임) ==============
document.addEventListener('click', (e) => {
  const btn = e.target.closest && e.target.closest('[data-card-menu-btn]');
  const openMenus = document.querySelectorAll('[data-card-menu].open');
  if (btn) {
    const menu = btn.parentElement.querySelector('[data-card-menu]');
    openMenus.forEach((m) => { if (m !== menu) m.classList.remove('open'); });
    if (menu) menu.classList.toggle('open');
    return;
  }
  // 메뉴 항목 클릭 포함, 그 외 어디를 눌러도 닫힘
  openMenus.forEach((m) => m.classList.remove('open'));
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
  if (icon) icon.setAttribute('icon', next === 'dark' ? 'solar:sun-bold' : 'solar:moon-bold');
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

// ============== 세그먼트 컨트롤 (탭과 동일 위임, pill 모양) ==============
document.addEventListener('click', (e) => {
  const t = e.target.closest && e.target.closest('[data-seg]');
  if (!t) return;
  const group = t.dataset.segGroup;
  document.querySelectorAll(`[data-seg][data-seg-group="${group}"]`)
    .forEach(el => el.classList.toggle('active', el === t));
  document.querySelectorAll(`[data-seg-panel][data-seg-group="${group}"]`)
    .forEach(el => el.classList.toggle('active', el.dataset.segPanel === t.dataset.seg));
});

// ============== 계획 검토 체크리스트 — 전부 체크해야 실행 활성화 ==============
document.addEventListener('change', (e) => {
  const input = e.target;
  if (!(input.matches && input.matches('[data-plan-check] input[type="checkbox"]'))) return;
  const scope = input.closest('[data-plan-checklist]');
  const cards = [...scope.querySelectorAll('[data-plan-check]')];
  cards.forEach((c) => {
    const on = c.querySelector('input').checked;
    c.style.borderColor = on ? 'var(--primary)' : '';
    c.style.background = on ? 'var(--primary-soft)' : '';
  });
  const n = cards.filter((c) => c.querySelector('input').checked).length;
  const run = scope.querySelector('[data-plan-run]');
  const hint = scope.querySelector('[data-plan-check-hint]');
  if (run) run.disabled = n < cards.length;
  if (hint) hint.textContent = n < cards.length
    ? `${cards.length}개 항목을 확인하면 실행할 수 있어요 (${n}/${cards.length})`
    : '모두 확인했어요 — 실행할 수 있어요';
});

// 실행 버튼 — hx-get으로 실험 상세(모의)로 이동. hx 속성이 없을 때만 안내 툴팁
document.addEventListener('click', (e) => {
  const t = e.target.closest && e.target.closest('[data-plan-run]');
  if (!t || t.disabled || t.hasAttribute('hx-get')) return;
  showFieldTooltip(t, '실행할 실험이 아직 없어요 (모의)');
});

// ============== 다이얼로그 ==============
function openDialog(name) {
  const d = document.getElementById(`dialog-${name}`);
  if (!d) return;
  d.classList.add('open');
  const card = d.querySelector('[data-wizard]');
  if (card) { wizReset(card); applyDialogSize(card); }  // 열 때마다 step1 리셋 + 저장 크기 재적용
}
function closeDialog(name) { const d = document.getElementById(`dialog-${name}`); if (d) d.classList.remove('open'); }
document.addEventListener('click', (e) => {
  if (e.target.classList && e.target.classList.contains('dialog-backdrop')) e.target.classList.remove('open');
});

// ── 등록 모달: 3-step 위저드 (클라이언트 show/hide, submit은 마지막 1회) ──
const WIZ_STEPS = 3;  // 기본값 — dialog-card의 data-wiz-steps로 카드별 재정의
function wizStepCount(card) { return +(card.dataset.wizSteps || WIZ_STEPS); }
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
  if (next) next.classList.toggle('hidden', step === wizStepCount(card));
  if (submit) submit.classList.toggle('hidden', step !== wizStepCount(card));
}
function wizReset(card) { card.dataset.wizStep = '1'; wizRender(card); }
function wizGo(card, dir) {
  let step = +(card.dataset.wizStep || 1);
  if (dir > 0) {  // 다음 누를 때 현재 패널 필수값 검증
    const panel = card.querySelector(`[data-wiz-panel="${step}"]`);
    const bad = [...panel.querySelectorAll('[data-wiz-required]')].find((i) => !i.disabled && !i.value.trim());
    if (bad) { showFieldTooltip(bad, bad.dataset.wizMsg || '입력해 주세요'); bad.focus(); return; }
  }
  card.dataset.wizStep = String(Math.min(wizStepCount(card), Math.max(1, step + dir)));
  wizRender(card);
}
document.addEventListener('click', (e) => {
  const next = e.target.closest('[data-wiz-next]');
  const prev = e.target.closest('[data-wiz-prev]');
  if (next) wizGo(next.closest('[data-wizard]'), +1);
  else if (prev) wizGo(prev.closest('[data-wizard]'), -1);
});

// ── 필드 검증 툴팁 (브라우저 기본 대신 커스텀, mate 스타일) ──
function hideFieldTooltip() {
  const t = document.getElementById('field-tooltip');
  if (t) t.remove();
}
function showFieldTooltip(target, message) {
  hideFieldTooltip();
  const tip = document.createElement('div');
  tip.id = 'field-tooltip';
  tip.className = 'field-tooltip';
  tip.textContent = message;
  document.body.appendChild(tip);
  const r = target.getBoundingClientRect();  // 모달은 fixed → 스크롤 보정 불필요
  tip.style.top = `${r.top - tip.offsetHeight - 8}px`;
  tip.style.left = `${r.left + r.width / 2 - tip.offsetWidth / 2}px`;
  target.addEventListener('input', hideFieldTooltip, { once: true });
  setTimeout(hideFieldTooltip, 3000);
}

// ── 모달 우측 하단 모서리 드래그 리사이즈 (가로·세로) ──
// 크기는 모듈 변수에 보관 → HTMX 스왑 간에는 유지, 풀 리프레시 시 초기화.
let _dialogW = null, _dialogH = null;
function applyDialogSize(card) {
  if (!card) return;
  if (_dialogW) { card.style.maxWidth = 'none'; card.style.width = `${_dialogW}px`; }
  if (_dialogH) { card.style.maxHeight = 'none'; card.style.height = `${_dialogH}px`; }
}
document.addEventListener('mousedown', (e) => {
  const handle = e.target.closest('.dialog-resize-handle');
  if (!handle) return;
  e.preventDefault();
  const card = handle.closest('.dialog-card');
  const startX = e.clientX, startY = e.clientY;
  const startW = card.offsetWidth, startH = card.offsetHeight;
  // 현재 크기를 먼저 px로 고정 → max 해제 시 width:100%로 순간 확대되는 '팍 튀는' 현상 방지
  card.style.width = `${startW}px`; card.style.height = `${startH}px`;
  card.style.maxWidth = 'none'; card.style.maxHeight = 'none';
  document.body.style.userSelect = 'none';
  const onMove = (ev) => {
    // flex-center 보정: 카드가 양쪽으로 커지므로 delta를 2배 적용해 모서리가 커서를 따라오게
    _dialogW = Math.max(360, Math.min(window.innerWidth - 32, Math.round(startW + 2 * (ev.clientX - startX))));
    _dialogH = Math.max(280, Math.min(window.innerHeight - 32, Math.round(startH + 2 * (ev.clientY - startY))));
    card.style.width = `${_dialogW}px`;
    card.style.height = `${_dialogH}px`;
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

// ── 등록 폼 환경변수: KEY=VALUE 텍스트 → env_json (시크릿은 키 이름으로 자동 감지) ──
const ENV_SECRET_RE = /(TOKEN|SECRET|PASSWORD|KEY)/i;

function envSyncFromText() {
  const ta = document.getElementById('env-paste');
  const json = document.getElementById('env-json');
  if (!ta || !json) return;
  const rows = ta.value.split('\n').map((line) => {
    const i = line.indexOf('=');
    if (i < 1) return null;
    const key = line.slice(0, i).trim();
    if (!key) return null;
    return { key, value: line.slice(i + 1).trim(), is_secret: ENV_SECRET_RE.test(key) };
  }).filter(Boolean);
  json.value = JSON.stringify(rows);
}
document.addEventListener('input', (e) => {
  if (e.target.id === 'env-paste') envSyncFromText();
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

// ── 새 실험 다이얼로그: 카오스 타입 선택 → 해당 파라미터 패널만 표시 ──
function chaosTypeSync(root) {
  const checked = root.querySelector('input[name="chaos_type"]:checked');
  if (!checked) return;
  root.querySelectorAll('.chaos-type-card').forEach((card) => {
    const on = card.querySelector('input').checked;
    card.style.borderColor = on ? 'var(--primary)' : '';
    card.style.background = on ? 'var(--primary-soft)' : '';
  });
  root.querySelectorAll('[data-chaos-fields]').forEach((panel) => {
    const on = panel.dataset.chaosFields === checked.value;
    panel.classList.toggle('hidden', !on);
    panel.querySelectorAll('input').forEach((i) => { i.disabled = !on; });
  });
}
document.addEventListener('change', (e) => {
  if (e.target.name === 'chaos_type') chaosTypeSync(e.target.closest('form'));
});

// ── 새 실험 위저드: 대상 앱 카드 강조 (설계는 항상 AI 후보 선택형 — ADR-0006) ──
function appPickSync(root) {
  root.querySelectorAll('.app-pick-card').forEach((card) => {
    const on = card.querySelector('input').checked;
    card.style.borderColor = on ? 'var(--primary)' : '';
    card.style.background = on ? 'var(--primary-soft)' : '';
  });
}
document.addEventListener('change', (e) => {
  if (e.target.name === 'app_id') appPickSync(e.target.closest('form'));
});

function newExperimentSync() {
  document.querySelectorAll('#dialog-newExperiment form').forEach(appPickSync);
}
document.body.addEventListener('htmx:afterSwap', newExperimentSync);
document.addEventListener('DOMContentLoaded', newExperimentSync);

// ── k3s 2단계 환경 준비: 후보 선택을 마친 뒤에만 서버가 전용 namespace를 준비한다. ──
let _preparationStream = null;
let _scenarioRunStream = null;
function closePreparationStream() {
  if (_preparationStream) { _preparationStream.close(); _preparationStream = null; }
}
function closeScenarioRunStream() {
  if (_scenarioRunStream) { _scenarioRunStream.close(); _scenarioRunStream = null; }
}
function renderPreparation(root, payload) {
  const progress = payload.progress || {};
  const message = root.querySelector('[data-prepare-message]');
  const namespace = root.querySelector('[data-prepare-namespace]');
  const pods = root.querySelector('[data-prepare-pods]');
  const error = root.querySelector('[data-prepare-error]');
  const blockers = root.querySelector('[data-prepare-blockers]');
  const status = root.querySelector('[data-prepare-status]');
  if (message) message.textContent = progress.message || '실험 환경 상태를 확인 중';
  if (namespace) namespace.textContent = payload.namespace ? `namespace: ${payload.namespace}` : '';
  if (pods && progress.pods_total != null) pods.textContent = `${progress.pods_ready || 0} / ${progress.pods_total} Pod Ready`;
  if (error) { error.classList.toggle('hidden', !payload.error); error.textContent = payload.error || ''; }
  const items = progress.blockers || [];
  if (blockers) {
    blockers.classList.toggle('hidden', !items.length);
    blockers.textContent = items.map((item) => `${item.name}: ${item.reason}`).join(' · ');
  }
  const spinner = root.querySelector('[data-prepare-spinner]');
  if (spinner) spinner.setAttribute('icon', payload.status === 'ready' ? 'solar:check-circle-bold' : payload.status === 'failed' ? 'solar:danger-circle-bold' : 'solar:refresh-circle-bold');
  if (status) {
    status.textContent = payload.status === 'ready' ? '준비 완료' : payload.status === 'failed' ? '준비 실패' : '준비 중';
    status.className = `tds-badge ${payload.status === 'ready' ? 'badge-success' : payload.status === 'failed' ? 'badge-danger' : 'badge-info'}`;
  }
}
async function startPreparation(root) {
  if (root.dataset.preparing === 'true' || root.dataset.preparationSessionId) return true;
  const appId = root.dataset.workflowAppId;
  if (!appId) return true;
  const panel = root.querySelector('[data-preparation-panel]');
  if (panel) panel.open = true;
  try {
    const body = new URLSearchParams({app_id: appId, objective: root.dataset.workflowObjective || ''});
    const response = await fetch('/experiment-sessions', {method: 'POST', body});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || '환경 준비를 시작하지 못했습니다');
    root.dataset.preparationSessionId = String(payload.id);
    root.dataset.preparing = 'true';
    renderPreparation(root, payload);
    _preparationStream = new EventSource(`/experiment-sessions/${payload.id}/stream`);
    _preparationStream.addEventListener('progress', (event) => renderPreparation(root, JSON.parse(event.data)));
    _preparationStream.addEventListener('completed', (event) => {
      const done = JSON.parse(event.data);
      closePreparationStream();
      root.dataset.preparing = 'false';
      root.dataset.preparationStatus = done.status;
      renderPreparation(root, done);
      if (done.status === 'ready') maybePlayExecution(root);
    });
    _preparationStream.onerror = closePreparationStream;
    fetch(`/experiment-sessions/${payload.id}/start`, {method: 'POST'}).catch(() => {
      closePreparationStream();
      root.dataset.preparing = 'false';
      root.dataset.preparationStatus = 'failed';
      renderPreparation(root, {status: 'failed', error: '환경 준비를 시작하지 못했습니다'});
    });
    return true;
  } catch (error) {
    renderPreparation(root, {status: 'failed', error: error.message});
    return false;
  }
}
document.addEventListener('click', (e) => {
  const request = e.target.closest('[data-candidate-request]');
  if (!request || !window.htmx) return;
  const form = request.closest('form');
  const picked = form?.querySelector('input[name="app_id"]:checked');
  if (!picked) return;
  const appId = picked.value;
  const objective = form.querySelector('textarea[name="objective"]')?.value.trim() || '';
  closeDialog('newExperiment');
  // 시나리오 회귀 워크플로우는 order-resilience-lab 전용(regression.scenario_snapshot 제약)
  // — 그 외 앱은 가설 수립 흐름(POST /hypothesis)으로.
  if (picked.dataset.appName === 'order-resilience-lab') {
    htmx.ajax('GET', `/experiments/1?${new URLSearchParams({view: 'plan', app_id: appId, objective})}`, {
      target: '#main-content', swap: 'innerHTML', pushUrl: true,
    });
    return;
  }
  htmx.ajax('POST', '/hypothesis', {
    target: '#main-content', swap: 'innerHTML',
    values: {
      app_id: appId, objective,
      max_candidates: form.querySelector('input[name="max_candidates"]')?.value || '5',
      max_improvements: form.querySelector('input[name="max_improvements"]')?.value || '3',
    },
  });
});

// ── 새 앱 등록 위저드: 환경(k3s/EKS) 분기 — ADR-0003 ──
function clusterEnvSync(root) {
  const checked = root.querySelector('input[name="cluster_env"]:checked');
  if (!checked) return;
  root.querySelectorAll('.env-pick-card').forEach((card) => {
    const on = card.querySelector('input').checked;
    card.style.borderColor = on ? 'var(--primary)' : '';
    card.style.background = on ? 'var(--primary-soft)' : '';
  });
  root.querySelectorAll('[data-env-panel]').forEach((panel) => {
    const on = panel.dataset.envPanel === checked.value;
    panel.classList.toggle('hidden', !on);
    panel.querySelectorAll('input, textarea').forEach((i) => { i.disabled = !on; });
  });
  const eks = root.querySelector('[data-submit-eks]');
  const k3s = root.querySelector('[data-submit-k3s]');
  if (eks) eks.classList.toggle('hidden', checked.value !== 'eks');
  if (k3s) k3s.classList.toggle('hidden', checked.value !== 'k3s');
}
function k3sSampleSync(root) {
  const selected = root.querySelector('input[name="sample_id"]:checked');
  const name = root.querySelector('[data-k3s-app-name]');
  const healthPath = root.querySelector('[data-k3s-health-path]');
  if (!selected || !name || !healthPath) return;
  if (selected.value === 'order-resilience-lab') {
    name.value = 'order-resilience-lab';
    healthPath.value = '/orders';
  } else {
    if (name.value === 'order-resilience-lab') name.value = '';
    if (healthPath.value === '/orders') healthPath.value = '/healthz';
  }
}
document.addEventListener('change', (e) => {
  if (e.target.name === 'cluster_env') clusterEnvSync(e.target.closest('form'));
  if (e.target.name === 'sample_id') k3sSampleSync(e.target.closest('form'));
});
function newAppSync() {
  document.querySelectorAll('#dialog-newApp form').forEach((form) => {
    clusterEnvSync(form);
    k3sSampleSync(form);
  });
}
document.body.addEventListener('htmx:afterSwap', newAppSync);
document.addEventListener('DOMContentLoaded', newAppSync);

// ── 실험 상태 watch (running 행만 EventSource, 종료 시 목록 새로고침) ──
const _expStreams = new Set();
function watchExperiments() {
  document.querySelectorAll('[data-running-exp]').forEach((el) => {
    const id = el.dataset.runningExp;
    if (_expStreams.has(id)) return;
    _expStreams.add(id);
    const es = new EventSource(`/experiments/${id}/stream`);
    const refresh = el.dataset.runningExpRefresh || '/experiments';
    es.addEventListener('completed', () => {
      es.close(); _expStreams.delete(id);
      if (window.htmx) htmx.ajax('GET', refresh, { target: '#main-content', swap: 'innerHTML' });
    });
    es.onerror = () => { es.close(); _expStreams.delete(id); };
  });
}
document.addEventListener('DOMContentLoaded', watchExperiments);
document.body.addEventListener('htmx:afterSwap', watchExperiments);

// ── 사이드바 active 동기화 (HTMX 부분 스왑은 사이드바 DOM을 안 바꿈) ──
function syncSidebarActive() {
  const path = location.pathname;
  const items = [...document.querySelectorAll('.sidebar-nav-item')];
  // 루트는 정확히, 나머지는 하위경로(/experiments/3 등)까지 매칭 — 서버 active_nav와 동일.
  // /infra vs /infra/local처럼 매칭이 겹치면 가장 긴 href 하나만 활성화
  let best = null;
  items.forEach((a) => {
    const href = a.getAttribute('hx-get');
    const match = href === '/' ? path === '/' : path === href || path.startsWith(href + '/');
    if (match && (!best || href.length > best.getAttribute('hx-get').length)) best = a;
  });
  items.forEach((a) => a.classList.toggle('active', a === best));
}
document.addEventListener('DOMContentLoaded', syncSidebarActive);
document.body.addEventListener('htmx:afterSwap', syncSidebarActive);
document.body.addEventListener('htmx:historyRestore', syncSidebarActive);

// ── 카오스 워크플로우 UI 시안 (브라우저 상태만 변경, 서버 요청 없음) ──
function syncWorkflowStageState(root) {
  if (!root) return;
  const stages = [...root.querySelectorAll('[data-workflow-stage]')];
  const active = stages.find((stage) => stage.classList.contains('active')) || stages[0];
  if (!active) return;
  const currentIndex = Number(root.dataset.workflowCurrentStage || 1);
  stages.forEach((stage) => {
    const isActive = stage === active;
    stage.classList.toggle('is-complete', Number(stage.dataset.stageIndex) < currentIndex);
    stage.setAttribute('aria-selected', isActive ? 'true' : 'false');
  });

  const setText = (selector, value) => {
    const el = root.querySelector(selector);
    if (el) el.textContent = value;
  };
  setText('[data-workflow-view-label]', active.dataset.stageLabel);
  setText('[data-workflow-aside-view]', active.dataset.stageLabel);
}

function syncWorkflowCandidates(root) {
  if (!root) return;
  const candidates = [...root.querySelectorAll('[data-workflow-candidate]')];
  candidates.forEach((candidate) => {
    const card = candidate.closest('label')?.querySelector('[data-candidate-card]');
    if (card) card.classList.toggle('is-selected', candidate.checked);
  });
  const selectedCandidates = candidates.filter((candidate) => candidate.checked);
  const selectedIds = selectedCandidates.map((candidate) => candidate.dataset.candidateId);
  const selected = selectedIds.length;
  if (root.dataset.workflowSelectMode === 'single') {
    // 가설 셸: radio 1개 → CTA 활성. 요약·도움말 문구는 서버 렌더 유지 (선택 시에만 덮어씀)
    const next = root.querySelector('[data-workflow-selection-next]');
    if (!next) return; // CTA 없음 = 구체화 중·실험 시작됨 — 서버 렌더 문구 그대로 (checked+disabled radio가 있어도 덮어쓰지 않음)
    next.disabled = selected < 1;
    const summary = root.querySelector('[data-workflow-selection-summary]');
    if (summary && selected) summary.textContent = `"${selectedCandidates[0].dataset.candidateTitle}" 후보를 선택했어요`;
    return;
  }
  const maxSelected = Number(root.dataset.workflowMaxSelected || 3);
  candidates.forEach((candidate) => {
    const card = candidate.closest('label')?.querySelector('[data-candidate-card]');
    if (candidate.disabled && !candidate.dataset.limitDisabled) return;
    const limitDisabled = selected >= maxSelected && !candidate.checked;
    candidate.disabled = limitDisabled;
    if (limitDisabled) candidate.dataset.limitDisabled = 'true';
    else delete candidate.dataset.limitDisabled;
    if (card) card.classList.toggle('is-limit-disabled', limitDisabled);
  });
  const summary = root.querySelector('[data-workflow-selection-summary]');
  if (summary) summary.textContent = selected ? `${selected}개 후보를 선택했어요` : '아직 선택한 후보가 없어요';
  const help = root.querySelector('[data-workflow-selection-help]');
  if (help) help.textContent = selected >= maxSelected ? `최대 ${maxSelected}개를 선택했어요. 하나를 해제하면 다른 후보를 고를 수 있습니다.` : `시나리오를 구성할 실험을 2개 이상 선택해 주세요.`;
  const next = root.querySelector('[data-workflow-selection-next]');
  if (next) next.disabled = selected < 2;
  const count = root.querySelector('[data-workflow-selected-count]');
  if (count) count.textContent = `${selected}개`;
  const executeStage = root.querySelector('[data-workflow-stage="execute"]');
  if (executeStage && Number(root.dataset.workflowCurrentStage) < 2) {
    executeStage.disabled = selected < 2;
    executeStage.setAttribute('aria-disabled', selected < 2 ? 'true' : 'false');
    executeStage.title = selected < 2 ? '실험을 2개 이상 선택하면 열립니다' : '';
  }
  root.dataset.selectedCandidateIds = selectedIds.join(',');
  syncWorkflowExecutionSelection(root, selectedIds);
}

function regressionStatusLabel(status, verdict) {
  if (status === 'completed' && verdict === 'passed') return ['badge-success', '전체 통과'];
  if (status === 'completed' && verdict === 'failed') return ['badge-danger', '기준 미충족'];
  if (status === 'completed' && verdict === 'inconclusive') return ['badge-warning', '판정 불가 포함'];
  if (status === 'completed') return ['badge-success', '실행 완료'];
  if (status === 'failed') return ['badge-danger', '실패'];
  return ['badge-info', '진행 중'];
}

function regressionStepState(spec, result, progress, roundName) {
  if (result) {
    if (result.status === 'passed') return ['badge-success', '통과'];
    if (result.status === 'inconclusive') return ['badge-warning', '판정 불가'];
    return ['badge-danger', '실패'];
  }
  if (progress.round === roundName && progress.experiment_id === spec.id) {
    const running = {
      observing: '관측 중',
      running: '실행 중',
      recovering: '복구 확인',
      cleanup: '정리 중',
    }[progress.stage] || '준비 중';
    return ['badge-info', running];
  }
  if (roundName === 'final' && progress.round === 'improvement') return ['badge-info', '개선 적용 대기'];
  return ['badge-muted', '대기'];
}

function appendRegressionRow(tbody, spec, baselineResult, finalResult, progress) {
  if (!tbody) return;
  const row = document.createElement('tr');
  row.dataset.regressionScenarioId = spec.id;
  row.className = 'border-t';
  row.style.borderColor = 'var(--border)';
  const values = [
    [spec.title, finalResult?.crd_name || baselineResult?.crd_name || ''],
    [Object.values(spec.target_selector || {}).join(', ') || 'namespace 전체', ''],
    [spec.chaos_type || '', ''],
  ];
  values.forEach(([primary, secondary], index) => {
    const cell = document.createElement('td');
    cell.className = index === 0 ? 'px-5 py-4' : 'px-5 py-4 text-xs';
    const text = document.createElement(index === 0 ? 'b' : 'span');
    text.textContent = primary;
    cell.appendChild(text);
    if (secondary) {
      const sub = document.createElement('div');
      sub.className = 'text-[11px] mono mt-1';
      sub.style.color = 'var(--muted-foreground)';
      sub.textContent = secondary;
      cell.appendChild(sub);
    }
    row.appendChild(cell);
  });
  [
    regressionStepState(spec, baselineResult, progress, 'baseline'),
    regressionStepState(spec, finalResult, progress, 'final'),
  ].forEach(([badgeClass, label]) => {
    const cell = document.createElement('td');
    cell.className = 'px-5 py-4 text-center';
    const badge = document.createElement('span');
    badge.className = `tds-badge ${badgeClass}`;
    badge.textContent = label;
    cell.appendChild(badge);
    row.appendChild(cell);
  });
  tbody.appendChild(row);
}

function renderRegressionRows(tbody, scenario, baselineResults, results, progress) {
  if (!tbody) return;
  const baselineByScenarioId = new Map((baselineResults || []).map((item) => [item.scenario_experiment_id, item]));
  const resultByScenarioId = new Map((results || []).map((item) => [item.scenario_experiment_id, item]));
  tbody.replaceChildren();
  (scenario?.experiments || []).forEach((spec) => {
    appendRegressionRow(tbody, spec, baselineByScenarioId.get(spec.id), resultByScenarioId.get(spec.id), progress);
  });
}

function renderScenarioRun(root, payload) {
  const progress = payload.progress || {};
  const total = payload.scenario?.experiments?.length || progress.total || 0;
  const finished = (payload.baseline_results || []).length + (payload.results || []).length;
  const succeeded = (payload.results || []).filter((item) => item.status === 'passed').length;
  const count = root.querySelector('[data-regression-count]');
  const message = root.querySelector('[data-regression-message]');
  const bar = root.querySelector('[data-regression-progress]');
  const status = root.querySelector('[data-regression-status]');
  const tbody = root.querySelector('[data-regression-results]');
  const empty = root.querySelector('[data-regression-empty]');
  const error = root.querySelector('[data-regression-error]');
  if (count) count.textContent = `${succeeded}/${total}`;
  const verdict = payload.comparison?.verdict;
  if (message) message.textContent = payload.status === 'completed' ? '개선 전후 최종 회귀 검증이 완료됐습니다' : (payload.status === 'failed' ? '최종 회귀 검증을 완료하지 못했습니다' : (progress.message || '최종 회귀 상태를 확인하고 있습니다'));
  if (bar) bar.style.width = `${total ? Math.round(finished / (total * 2) * 100) : 0}%`;
  const [badge, label] = regressionStatusLabel(payload.status, verdict);
  if (status) { status.className = `tds-badge ${badge}`; status.textContent = label; }
  renderRegressionRows(tbody, payload.scenario, payload.baseline_results, payload.results, progress);
  if (empty) empty.classList.toggle('hidden', total > 0);
  if (error) {
    error.classList.toggle('hidden', !payload.error);
    error.textContent = payload.error || '';
  }
  const terminal = payload.status === 'completed' || payload.status === 'failed';
  const result = root.querySelector('[data-regression-result]');
  if (result) result.disabled = !terminal;
  const resultStage = root.querySelector('[data-workflow-stage="result"]');
  if (resultStage && terminal) {
    resultStage.disabled = false;
    resultStage.setAttribute('aria-disabled', 'false');
    resultStage.title = '';
    root.dataset.workflowCurrentStage = '4';
  }
}

function watchScenarioRun(root, runId) {
  closeScenarioRunStream();
  _scenarioRunStream = new EventSource(`/scenario-runs/${runId}/stream`);
  _scenarioRunStream.addEventListener('progress', (event) => renderScenarioRun(root, JSON.parse(event.data)));
  _scenarioRunStream.addEventListener('completed', (event) => {
    renderScenarioRun(root, JSON.parse(event.data));
    closeScenarioRunStream();
  });
  _scenarioRunStream.onerror = closeScenarioRunStream;
}

async function startScenarioRun(root) {
  if (root.dataset.scenarioRunId) return true;
  const sessionId = root.dataset.preparationSessionId;
  const hypothesisRun = root.dataset.hypothesisRun || '';
  // 가설 경로는 승인 후보로 서버가 조립 — selected_ids 대신 hypothesis_run_id
  const selectedIds = hypothesisRun ? '' : (root.dataset.selectedCandidateIds || '');
  if (!sessionId) return false;
  try {
    const body = new URLSearchParams({session_id: sessionId, selected_ids: selectedIds});
    if (hypothesisRun) body.set('hypothesis_run_id', hypothesisRun);
    const response = await fetch('/scenario-runs', {method: 'POST', body});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || '최종 회귀를 시작하지 못했습니다');
    root.dataset.scenarioRunId = String(payload.id);
    const url = hypothesisRun
      ? new URL(`/hypothesis/${hypothesisRun}`, window.location.origin)
      : new URL(window.location.href);
    url.searchParams.set('view', 'verify');
    url.searchParams.set('scenario_run_id', payload.id);
    history.replaceState({}, '', url);
    const setup = root.querySelector('[data-hypothesis-regression-setup]');
    if (setup) setup.classList.add('hidden');
    renderScenarioRun(root, payload);
    watchScenarioRun(root, payload.id);
    return true;
  } catch (error) {
    const panel = root.querySelector('[data-regression-error]');
    if (panel) { panel.classList.remove('hidden'); panel.textContent = error.message; }
    return false;
  }
}

// 가설 경로 3단계: 준비 세션(ready) → 승인 후보 회귀 시작. startPreparation은 스트림만 열고
// 바로 돌아오므로 dataset(preparing·preparationStatus)으로 종료를 기다린다.
function waitPreparation(root) {
  return new Promise((resolve) => {
    const tick = () => {
      if (root.dataset.preparing === 'true') { setTimeout(tick, 500); return; }
      resolve(root.dataset.preparationStatus || (root.dataset.preparationSessionId ? 'ready' : 'failed'));
    };
    tick();
  });
}
async function startHypothesisRegression(root) {
  if (!await startPreparation(root)) return false;
  const status = await waitPreparation(root);
  if (status !== 'ready') {
    // 실패한 세션은 버리고 다음 클릭에서 새 세션을 만들 수 있게
    delete root.dataset.preparationSessionId;
    delete root.dataset.preparationStatus;
    return false;
  }
  return startScenarioRun(root);
}

function syncWorkflowExecutionSelection(root, selectedIds) {
  const queueItems = [...root.querySelectorAll('[data-execution-queue-item]')];
  queueItems.forEach((item) => {
    const order = selectedIds.indexOf(item.dataset.executionQueueItem);
    const selected = order >= 0;
    item.classList.toggle('hidden', !selected);
    item.classList.toggle('is-current', order === 0);
    const orderEl = item.querySelector('[data-queue-order]');
    if (orderEl && selected) orderEl.textContent = String(order + 1);
    const status = item.querySelector('[data-queue-status]');
    if (status && selected) status.textContent = order === 0 ? '현재 상세 · 개선 1회 예시' : '다음 실행 · 대기';
  });
  const empty = root.querySelector('[data-workflow-queue-empty]');
  if (empty) empty.classList.toggle('hidden', selectedIds.length > 0);
  root.querySelectorAll('[data-candidate-execution]').forEach((panel) => {
    panel.classList.toggle('hidden', panel.dataset.candidateExecution !== selectedIds[0]);
  });
  const executionCount = root.querySelector('[data-workflow-execution-count]');
  if (executionCount) executionCount.textContent = selectedIds.length ? `${selectedIds.length}개 선택 · 화면 예시` : '후보 선택 필요';
  maybePlayExecution(root);
}

// ── 실행 탭 모의 실행 애니메이션 (시안) — 6단계 파이프라인이 실제 도는 듯한 연출 ──
const EXEC_STEP_MS = 950;
const EXEC_TIMELINE = [
  { badge: ['badge-info', '기준선 관측 중'] },
  { badge: ['badge-warning', '장애 주입 중'] },
  { badge: ['badge-info', '정리 확인 중'] },
  { badge: ['badge-danger', '초기 판정 실패'] },
  { badge: ['badge-info', 'AI 분석·개선 중'], reveal: true, attempt: 'attempt 2 / 3' },
  { badge: ['badge-warning', '동조건 재실험 중'] },
];

function execFinish(card) {
  card.querySelectorAll('[data-exec-step]').forEach((s) => s.classList.remove('exec-pending', 'exec-active'));
  card.querySelectorAll('[data-exec-after]').forEach((a) => a.classList.remove('exec-hidden'));
  const analysis = card.querySelector('[data-exec-analysis]');
  if (analysis) analysis.classList.remove('exec-hidden');
  const badge = card.querySelector('[data-exec-status]');
  if (badge) { badge.className = 'tds-badge badge-success'; badge.textContent = '재실험 통과'; }
  const attempt = card.querySelector('[data-exec-attempt]');
  if (attempt) attempt.textContent = 'attempt 2 / 3';
}

function playExecutionDemo(card) {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) { execFinish(card); return; }
  const steps = [...card.querySelectorAll('[data-exec-step]')];
  const badge = card.querySelector('[data-exec-status]');
  const attempt = card.querySelector('[data-exec-attempt]');
  const analysis = card.querySelector('[data-exec-analysis]');
  steps.forEach((s) => s.classList.add('exec-pending'));
  card.querySelectorAll('[data-exec-after]').forEach((a) => a.classList.add('exec-hidden'));
  if (analysis) analysis.classList.add('exec-hidden');
  if (attempt) attempt.textContent = 'attempt 1 / 3';
  steps.forEach((step, i) => {
    setTimeout(() => {
      steps.forEach((s) => s.classList.remove('exec-active'));
      step.classList.remove('exec-pending');
      step.classList.add('exec-active');
      const t = EXEC_TIMELINE[i] || {};
      if (badge && t.badge) { badge.className = `tds-badge ${t.badge[0]} exec-live`; badge.textContent = t.badge[1]; }
      if (t.reveal && analysis) analysis.classList.remove('exec-hidden');
      if (t.attempt && attempt) attempt.textContent = t.attempt;
    }, i * EXEC_STEP_MS);
  });
  setTimeout(() => execFinish(card), steps.length * EXEC_STEP_MS + 400);
}

// 실행 탭이 보일 때 현재 표시 중인 실험 카드를 1회 재생 (카드별 1번만)
function maybePlayExecution(root) {
  if (!root) return;
  if (root.dataset.preparing === 'true') return;
  const section = root.querySelector('[data-tab-content="execute"]');
  if (!section || !section.classList.contains('active')) return;
  const card = section.querySelector('[data-candidate-execution]:not(.hidden)');
  if (!card || card.dataset.execPlayed) return;
  card.dataset.execPlayed = 'true';
  playExecutionDemo(card);
}

function syncCandidatePrompt(root) {
  if (!root) return;
  const prompt = root.querySelector('[data-candidate-prompt]');
  const generate = root.querySelector('[data-candidate-generate]');
  if (!prompt || !generate) return;
  const value = prompt.value.trim();
  generate.disabled = !value || value === generate.dataset.lastPrompt;
  const count = root.querySelector('[data-candidate-prompt-count]');
  if (count) count.textContent = `${prompt.value.length} / 200`;
}

function showGeneratedCandidate(root) {
  const prompt = root?.querySelector('[data-candidate-prompt]');
  const generate = root?.querySelector('[data-candidate-generate]');
  const generated = root?.querySelector('[data-generated-candidate]');
  const value = prompt?.value.trim();
  if (!root || !generate || !generated || !value) return;
  generated.classList.remove('hidden');
  const promptText = generated.querySelector('[data-generated-prompt-text]');
  if (promptText) promptText.textContent = `“${value}”`;
  const total = root.querySelector('[data-workflow-candidate-total]');
  if (total) total.textContent = '4개 후보 · 예시';
  const label = generate.querySelector('[data-candidate-generate-label]');
  if (label) label.textContent = '다른 예시로 갱신';
  generate.dataset.lastPrompt = value;
  syncCandidatePrompt(root);
  syncWorkflowCandidates(root);
}

function initWorkflowDemo() {
  document.querySelectorAll('[data-workflow-shell]').forEach((root) => {
    syncWorkflowStageState(root);
    syncWorkflowCandidates(root);
    syncCandidatePrompt(root);
    if (root.dataset.scenarioRunId) watchScenarioRun(root, root.dataset.scenarioRunId);
  });
}

document.addEventListener('click', async (e) => {
  const promptExample = e.target.closest && e.target.closest('[data-candidate-prompt-example]');
  if (promptExample) {
    const root = promptExample.closest('[data-workflow-shell]');
    const prompt = root?.querySelector('[data-candidate-prompt]');
    if (prompt) {
      prompt.value = promptExample.dataset.candidatePromptExample;
      syncCandidatePrompt(root);
      prompt.focus();
    }
    return;
  }

  const generate = e.target.closest && e.target.closest('[data-candidate-generate]');
  if (generate && !generate.disabled) {
    showGeneratedCandidate(generate.closest('[data-workflow-shell]'));
    return;
  }

  const stage = e.target.closest && e.target.closest('[data-workflow-stage]');
  if (stage) {
    const shell = stage.closest('[data-workflow-shell]');
    syncWorkflowStageState(shell);
    maybePlayExecution(shell);
  }

  const hypStart = e.target.closest && e.target.closest('[data-hypothesis-regression-start]');
  if (hypStart) {
    if (hypStart.disabled) return;
    const root = hypStart.closest('[data-workflow-shell]');
    hypStart.disabled = true;
    if (!await startHypothesisRegression(root)) hypStart.disabled = false;
    return;
  }

  const go = e.target.closest && e.target.closest('[data-workflow-go]');
  if (!go || go.disabled) return;
  const root = go.closest('[data-workflow-shell]');
  const target = root?.querySelector(`[data-workflow-stage="${go.dataset.workflowGo}"]`);
  if (target) {
    // 가설 경로는 2단계 실험이 이미 끝난 상태 — 준비 세션은 3단계 회귀 시작 버튼이 만든다
    if (go.dataset.workflowGo === 'execute' && root.dataset.workflowAppEnv === 'k3s' && !root.dataset.hypothesisRun) {
      if (!await startPreparation(root)) return;
    }
    if (go.hasAttribute('data-regression-start')) {
      if (!await startScenarioRun(root)) return;
      target.disabled = false;
      target.setAttribute('aria-disabled', 'false');
      target.title = '';
      root.dataset.workflowCurrentStage = '3';
    }
    if (go.hasAttribute('data-workflow-preview-unlock')) {
      target.disabled = false;
      target.setAttribute('aria-disabled', 'false');
      target.title = '';
    }
    target.click();
    root.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
});

document.addEventListener('click', (e) => {
  const result = e.target.closest && e.target.closest('[data-regression-result]');
  if (!result || result.disabled || !window.htmx) return;
  const root = result.closest('[data-workflow-shell]');
  const runId = root?.dataset.scenarioRunId;
  if (!runId) return;
  const resultUrl = root.dataset.hypothesisRun
    ? `/hypothesis/${root.dataset.hypothesisRun}?view=result`
    : `/experiments/${root.dataset.workflowRunId}?view=result&scenario_run_id=${runId}`;
  htmx.ajax('GET', resultUrl, {target: '#main-content', swap: 'innerHTML', pushUrl: true});
});

document.addEventListener('change', (e) => {
  if (e.target.matches && e.target.matches('[data-workflow-candidate]')) {
    syncWorkflowCandidates(e.target.closest('[data-workflow-shell]'));
  }
});

document.addEventListener('input', (e) => {
  if (e.target.matches && e.target.matches('[data-candidate-prompt]')) {
    syncCandidatePrompt(e.target.closest('[data-workflow-shell]'));
  }
});

document.addEventListener('DOMContentLoaded', initWorkflowDemo);
document.body.addEventListener('htmx:afterSwap', initWorkflowDemo);

// ── 가설 수립 watch (생성·직접입력·구체화 진행 중일 때만 EventSource) ──
const _hypStreams = new Set();
function watchHypothesis() {
  document.querySelectorAll('[data-hypothesis-active]').forEach((el) => {
    const id = el.dataset.hypothesisRun;
    if (_hypStreams.has(id)) return;
    _hypStreams.add(id);
    const refresh = el.dataset.hypothesisRefresh || `/hypothesis/${id}`;
    const es = new EventSource(`/hypothesis/${id}/stream`);
    let first = true; // 최초 스냅샷은 방금 렌더된 화면과 같음 — 재요청 생략
    es.addEventListener('status', () => {
      if (first) { first = false; return; }
      if (window.htmx) htmx.ajax('GET', refresh, { target: '#main-content', swap: 'innerHTML' });
    });
    es.addEventListener('completed', (e) => {
      es.close(); _hypStreams.delete(id);
      let redirect = '';
      try { redirect = JSON.parse(e.data).redirect || ''; } catch (err) { /* noop */ }
      // 실험이 만들어지면 2단계로 착지 (URL도 맞춰 둔다 — 새로고침 시 같은 탭)
      if (redirect) history.replaceState({}, '', redirect);
      if (window.htmx) htmx.ajax('GET', redirect || refresh, { target: '#main-content', swap: 'innerHTML' });
    });
    es.onerror = () => { es.close(); _hypStreams.delete(id); };
  });
}
document.addEventListener('DOMContentLoaded', watchHypothesis);
document.body.addEventListener('htmx:afterSwap', watchHypothesis);

// ── 실험 진행 중 실시간 메트릭 (data-live-metrics → /experiments/{id}/metrics/stream) ──
// 화면에 실행 카드는 1개 — 전역 스트림 1개만 유지, 스왑으로 요소가 바뀌면 이전 스트림을 닫고 다시 구독.
let _liveMetricsStream = null;
function watchLiveMetrics() {
  const el = document.querySelector('[data-live-metrics]');
  if (_liveMetricsStream) {
    if (_liveMetricsStream._el === el) return;   // 같은 요소 — 구독 유지
    _liveMetricsStream.close(); _liveMetricsStream = null;
  }
  if (!el || el.dataset.liveMetricsFinal === 'true' || typeof Chart === 'undefined') return;

  const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const WINDOW = 60;  // rolling window — 최근 60틱(3s × 60 = 3분)
  const cc = chartCommon();
  const line = (color, yAxisID) => ({ data: [], borderColor: color, backgroundColor: color + '22', fill: false, tension: 0.3, pointRadius: 0, borderWidth: 2, spanGaps: true, yAxisID });
  const latency = new Chart(el.querySelector('[data-live-metrics-latency]'), {
    type: 'line',
    data: { labels: [], datasets: [line(cssVar('--warning'), 'y'), line(cssVar('--danger'), 'y')] },
    options: { ...cc, animation: false, scales: { ...cc.scales, x: { display: false }, y: { ...cc.scales.y, min: 0 } } }
  });
  const traffic = new Chart(el.querySelector('[data-live-metrics-traffic]'), {
    type: 'line',
    data: { labels: [], datasets: [line(cssVar('--primary'), 'y'), line(cssVar('--danger'), 'y1')] },
    options: { ...cc, animation: false, scales: { ...cc.scales, x: { display: false }, y: { ...cc.scales.y, min: 0 },
      y1: { position: 'right', min: 0, grid: { display: false }, ticks: { color: tdsTextColor(), font: { size: 10 }, callback: (v) => `${v}%` } } } }
  });
  const push = (chart, values, label) => {
    chart.data.labels.push(label);
    values.forEach((v, i) => chart.data.datasets[i].data.push(v));
    if (chart.data.labels.length > WINDOW) { chart.data.labels.shift(); chart.data.datasets.forEach((d) => d.data.shift()); }
    chart.update();
  };
  const pods = el.querySelector('[data-live-metrics-pods]');

  const es = new EventSource(`/experiments/${el.dataset.liveMetrics}/metrics/stream`);
  es._el = el;
  es.addEventListener('metric', (e) => {
    let m = {};
    try { m = JSON.parse(e.data); } catch (err) { return; }
    const label = (m.ts || '').slice(11, 19);
    push(latency, [m.p95_ms, m.p99_ms], label);
    push(traffic, [m.rps, m.error_rate_pct], label);
    if (pods) pods.textContent = m.ready_pods == null ? '-' : m.ready_pods;
  });
  // completed 이후 화면 재요청은 watchExperiments(status 스트림)가 담당 — 여기선 스트림만 닫고 차트를 남긴다.
  es.addEventListener('completed', () => { es.close(); if (_liveMetricsStream === es) _liveMetricsStream = null; });
  es.onerror = () => { es.close(); if (_liveMetricsStream === es) _liveMetricsStream = null; };
  _liveMetricsStream = es;
}
document.addEventListener('DOMContentLoaded', watchLiveMetrics);
document.body.addEventListener('htmx:afterSwap', watchLiveMetrics);
