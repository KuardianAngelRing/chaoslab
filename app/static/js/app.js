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
    if (bad) { showFieldTooltip(bad, bad.dataset.wizMsg || '입력해 주세요'); bad.focus(); return; }
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
document.body.addEventListener('htmx:afterSwap', () => {
  document.querySelectorAll('#dialog-newExperiment form').forEach(chaosTypeSync);
});
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('#dialog-newExperiment form').forEach(chaosTypeSync);
});

// ── 실험 상태 watch (running 행만 EventSource, 종료 시 목록 새로고침) ──
const _expStreams = new Set();
function watchExperiments() {
  document.querySelectorAll('[data-running-exp]').forEach((el) => {
    const id = el.dataset.runningExp;
    if (_expStreams.has(id)) return;
    _expStreams.add(id);
    const es = new EventSource(`/experiments/${id}/stream`);
    es.addEventListener('completed', () => {
      es.close(); _expStreams.delete(id);
      if (window.htmx) htmx.ajax('GET', '/experiments', { target: '#main-content', swap: 'innerHTML' });
    });
    es.onerror = () => { es.close(); _expStreams.delete(id); };
  });
}
document.addEventListener('DOMContentLoaded', watchExperiments);
document.body.addEventListener('htmx:afterSwap', watchExperiments);

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
  if (help) help.textContent = selected >= maxSelected ? `최대 ${maxSelected}개를 선택했어요. 하나를 해제하면 다른 후보를 고를 수 있습니다.` : `1개 이상, 최대 ${maxSelected}개까지 선택할 수 있습니다.`;
  const next = root.querySelector('[data-workflow-selection-next]');
  if (next) next.disabled = selected === 0;
  const count = root.querySelector('[data-workflow-selected-count]');
  if (count) count.textContent = `${selected}개`;
  const executeStage = root.querySelector('[data-workflow-stage="execute"]');
  if (executeStage && Number(root.dataset.workflowCurrentStage) < 3) {
    executeStage.disabled = selected === 0;
    executeStage.setAttribute('aria-disabled', selected === 0 ? 'true' : 'false');
    executeStage.title = selected === 0 ? '후보를 하나 이상 선택하면 열립니다' : '';
  }
  syncWorkflowExecutionSelection(root, selectedIds);
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
  });
}

document.addEventListener('click', (e) => {
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
  if (stage) syncWorkflowStageState(stage.closest('[data-workflow-shell]'));

  const go = e.target.closest && e.target.closest('[data-workflow-go]');
  if (!go || go.disabled) return;
  const root = go.closest('[data-workflow-shell]');
  const target = root?.querySelector(`[data-workflow-stage="${go.dataset.workflowGo}"]`);
  if (target) {
    if (go.hasAttribute('data-workflow-preview-unlock')) {
      target.disabled = false;
      target.setAttribute('aria-disabled', 'false');
      target.title = '';
    }
    target.click();
    root.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
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
