'use strict';

// Public demonstration only. No credentials, server sessions or signing keys.
(() => {
  const root = document.documentElement;
  const page = root.dataset.demoPortalPage;
  const roleKey = 'cardioinsight.demo.portal.role';
  const destinations = {diagnosis: 'workbench.html', review: 'review.html'};
  const requiredRole = {workbench: 'diagnosis', review: 'review'}[page];
  const caseId = 'math-4314-001';

  function currentRole() {
    try {
      const role = sessionStorage.getItem(roleKey);
      return Object.hasOwn(destinations, role) ? role : null;
    } catch {
      return null;
    }
  }

  function guardRole() {
    const role = currentRole();
    if (!requiredRole || role === requiredRole) return true;
    root.dataset.demoPortalBlocked = '';
    location.replace(destinations[role] || 'index.html');
    return false;
  }

  function showError(message) {
    const notice = document.querySelector('[data-demo-error]');
    if (notice) {
      notice.textContent = message;
      notice.hidden = false;
    }
  }

  function showReport() {
    const card = document.querySelector('[data-demo-report]');
    const empty = document.querySelector('[data-demo-report-empty]');
    const fingerprint = window.__CARDIOINSIGHT_SOURCE_VERSION__?.source_fingerprint;
    const storeKey = fingerprint ? `cardioinsight.math.${fingerprint}` : 'cardioinsight-public-math-4314-v2';
    let report;
    try {
      report = JSON.parse(localStorage.getItem(storeKey) || '{}')?.reports?.[caseId];
    } catch {
      card.hidden = true;
      empty.hidden = true;
      showError('无法读取浏览器中的演示报告。请检查站点存储设置。');
      return;
    }
    if (typeof report !== 'object' || Array.isArray(report)) report = null;

    document.querySelector('[data-demo-error]').hidden = true;
    card.hidden = !report;
    empty.hidden = Boolean(report);
    if (!report) return;

    const labels = {draft: '草稿', reviewed: '审核通过（演示）', returned: '已退回（演示）'};
    card.querySelector('[data-demo-report-status]').textContent = typeof report.status === 'string' && Object.hasOwn(labels, report.status) ? labels[report.status] : '已保存';
    card.querySelector('[data-demo-report-conclusion]').textContent =
      typeof report.conclusion === 'string' && report.conclusion.trim() ? report.conclusion : '尚无报告结论';
    const strips = Array.isArray(report.composition?.selected_events) ? report.composition.selected_events.length : 0;
    card.querySelector('[data-demo-report-strips]').textContent = `${strips} 张`;
    const hasVersion = Number.isSafeInteger(report.version) && report.version > 0;
    card.querySelector('[data-demo-report-version-row]').hidden = !hasVersion;
    if (hasVersion) card.querySelector('[data-demo-report-version]').textContent = String(report.version);

    const timestamp = typeof report.updated_at === 'string' ? Date.parse(report.updated_at) : NaN;
    card.querySelector('[data-demo-report-date-row]').hidden = !Number.isFinite(timestamp);
    if (Number.isFinite(timestamp)) {
      const time = card.querySelector('[data-demo-report-date]');
      time.dateTime = new Date(timestamp).toISOString();
      time.textContent = new Intl.DateTimeFormat('zh-CN', {dateStyle: 'medium', timeStyle: 'short'}).format(timestamp);
    }
  }

  function mountWorkbenchAccount() {
    const host = document.getElementById('demoAccountActions');
    const card = document.querySelector('.topbar .role-chip');
    if (card) {
      card.querySelector('strong').textContent = '诊断医生';
      card.querySelector('small').textContent = '演示登录';
    }
    if (!host) return;
    host.setAttribute('aria-label', '演示账号');
    const review = document.createElement('button');
    review.type = 'button';
    review.dataset.demoRole = 'review';
    review.textContent = '切换为审核医生';
    const logout = document.createElement('button');
    logout.type = 'button';
    logout.dataset.demoLogout = '';
    logout.textContent = '退出登录';
    host.replaceChildren(review, logout);
  }

  function bind() {
    if (!guardRole()) return;
    if (page === 'workbench') mountWorkbenchAccount();
    if (page === 'review') {
      showReport();
      window.addEventListener('storage', showReport);
    }

    document.addEventListener('click', event => {
      const button = event.target.closest('button[data-demo-role], button[data-demo-logout]');
      if (!button || button.disabled) return;
      const role = button.dataset.demoRole;
      if (role && !Object.hasOwn(destinations, role)) return;
      if (page === 'workbench' && typeof clinicalWorkflow !== 'undefined' && !clinicalWorkflow.allowLeave()) return;
      try {
        if (role) sessionStorage.setItem(roleKey, role);
        else sessionStorage.removeItem(roleKey);
      } catch {
        showError('浏览器无法保存演示登录状态。请检查站点存储设置后重试。');
        return;
      }
      location.assign(role ? destinations[role] : 'index.html');
    });
  }

  if (!guardRole()) return;
  document.addEventListener('DOMContentLoaded', bind, {once: true});
  window.addEventListener('pageshow', event => {
    if (event.persisted && guardRole() && page === 'review') showReport();
  });
})();
