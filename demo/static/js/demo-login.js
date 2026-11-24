'use strict';

// Bind the shared clinical workspace to the synthetic case and trial roles.
(() => {
  const root = document.documentElement;
  const trial = window.ECGDemoTrial;
  const role = trial.currentRole();
  const query = new URLSearchParams(location.search);
  const round = /^\d+$/.test(query.get('round') || '') ? Number(query.get('round')) : 0;
  const kind = query.get('kind') === 'signed' ? 'signed' : 'preview';
  const readPosts = new Set(['event-waveforms', 'waveform-density', 'scatter-selection', 'waveform-strips',
    'advanced-analysis', 'rr-review/locate', 'stt-range', 'report-evidence/preview']);
  const reviewing = role === 'review';
  const readOnly = reviewing || round > 0;
  let openedToken;

  function back() {
    root.dataset.trialBlocked = '';
    location.replace(trial.deskUrl());
  }

  function allowed() {
    if (!role || role !== trial.currentRole()) return false;
    if (round) return Boolean(trial.pastSubmission(round, kind));
    const {status, active} = trial.readWorkspace();
    const submitted = ['pending', 'signed'].includes(status);
    return reviewing ? submitted && Boolean(active) : !submitted;
  }

  try {
    if (!allowed()) {
      document.addEventListener('DOMContentLoaded', event => event.stopImmediatePropagation(), {capture: true, once: true});
      back();
      return;
    }
    openedToken = trial.readWorkspace().token;
    if (readOnly) root.dataset.reviewReadonly = '';
    if (round) {
      const {store, report} = trial.readWorkspace();
      const submitted = trial.pastSubmission(round, kind);
      const id = root.dataset.trialCase;
      window.ECGDemoTrialSnapshot = {...(submitted.evidence || store),
        reports: {[id]: {...report, version: submitted.clinical_version, conclusion: submitted.conclusion,
          updated_at: submitted.submitted, composition: submitted.composition, status: 'draft'}}};
    }
  } catch {
    document.addEventListener('DOMContentLoaded', event => event.stopImmediatePropagation(), {capture: true, once: true});
    back();
    return;
  }

  function bind() {
    // The mathematical data adapter has already installed its fetch handler.
    const mathFetch = window.fetch.bind(window);
    window.fetch = (input, options = {}) => {
      const path = new URL(input instanceof Request ? input.url : input, location.href).pathname;
      const method = String(options.method || input?.method || 'GET').toUpperCase();
      if (!path.startsWith('/api/') || method === 'GET' || method === 'HEAD') return mathFetch(input, options);
      const action = path.match(/^\/api\/cases\/[^/]+\/(.+)$/)?.[1];
      if (method === 'POST' && readPosts.has(action)) return mathFetch(input, options);
      if (readOnly && method === 'POST' && action === 'open') return Promise.resolve(Response.json({ok: true}));
      if (!readOnly && allowed()) return mathFetch(input, options);
      return Promise.resolve(Response.json({error: '送审报告处于只读复核状态。'}, {status: 403}));
    };
    const label = reviewing ? '审核' : '诊断';
    const deskLink = document.querySelector('[data-trial-leave]');
    deskLink.textContent = label + '工作台';
    deskLink.href = trial.deskUrl();
    const badge = document.querySelector('.role-chip');
    badge.querySelector('strong').textContent = label + '医生（测试）';
    badge.querySelector('small').textContent = readOnly ? '只读复核' : '浏览器账号验证';
    if (readOnly) loadLocalReportComposition = () => null;
    if (!round) return;
    // Use the actual report paper renderer as soon as the submitted report has loaded.
    const content = document.getElementById('page-report');
    const observer = new MutationObserver(async () => {
      const preview = content.querySelector('#reportV2Content [data-paper-preview]');
      if (!preview || state.reportEvidenceLoading || state.reportViewLoading) return;
      observer.disconnect();
      const submitted = trial.pastSubmission(round, kind);
      if (kind === 'signed' && submitted?.test_signature) {
        if (!await trial.verifySubmission(submitted).catch(() => false)) {
          handleError(new Error('浏览器演示签名校验失败，请重新核对送审版本。'));
          return;
        }
      }
      if (query.get('download') === '1') clinicalUI.print().catch(handleError);
      else preview.click();
    });
    observer.observe(content, {childList: true, subtree: true});
  }

  function checkContext() {
    try {
      if (!allowed() || (reviewing && !round && trial.readWorkspace().token !== openedToken)) back();
    } catch { back(); }
  }

  document.addEventListener('DOMContentLoaded', bind, {capture: true, once: true});
  window.addEventListener('storage', event => {
    if (!event.key || event.key === trial.storageKey()) checkContext();
  });
  window.addEventListener('pageshow', event => { if (event.persisted) checkContext(); });
})();
