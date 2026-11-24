'use strict';

// Public demonstration only. No credentials, server sessions or signing keys.
(() => {
  const root = document.documentElement;
  const page = root.dataset.demoPortalPage;
  const roleKey = 'cardioinsight.demo.portal.role';
  const destinations = {diagnosis: 'diagnosis.html', review: 'review.html'};
  const requiredRole = {diagnosis: 'diagnosis', workbench: 'diagnosis', review: 'review'}[page];
  const caseId = 'math-4314-001';
  const desk = page === 'diagnosis' || page === 'review';
  const labels = {draft: '待诊断', pending: '待审核', returned: '已退回', approved: '已通过（演示）'};
  const feedback = {save: '已保存演示草稿', submit: '已提交演示报告，请切换为审核医生', withdraw: '已撤回送审', return: '已退回诊断医生', approve: '演示审核已通过'};
  const allowed = {diagnosis: {draft: ['save', 'submit'], returned: ['save', 'submit'], pending: ['withdraw']}, review: {pending: ['approve', 'return']}};
  let viewed = null;
  let viewedConclusion = '';

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

  function allowWorkbench() {
    if (!guardRole()) return false;
    try {
      const {status} = readWorkspace();
      if (status !== 'pending' && status !== 'approved') return true;
    } catch {
      return true; // The shared workbench handles an unreadable local store.
    }
    root.dataset.demoPortalBlocked = '';
    location.replace(destinations.diagnosis);
    return false;
  }

  function showError(message) {
    const notice = document.querySelector('[data-demo-error]');
    if (notice) {
      notice.textContent = message;
      notice.hidden = false;
    } else if (typeof toast === 'function') toast(message, 'error');
  }

  function workspaceKey() {
    const fingerprint = window.__CARDIOINSIGHT_SOURCE_VERSION__?.source_fingerprint;
    return fingerprint ? `cardioinsight.math.${fingerprint}` : 'cardioinsight-public-math-4314-v2';
  }

  function readWorkspace() {
    const store = JSON.parse(localStorage.getItem(workspaceKey()) || '{}');
    if (!store || typeof store !== 'object' || Array.isArray(store)) throw Error('无法读取演示报告。');
    const report = store.reports?.[caseId];
    const flow = store.demoHandoff?.[caseId];
    const version = Number.isSafeInteger(report?.version) ? report.version : 1;
    const current = typeof flow?.state === 'string' && Object.hasOwn(labels, flow.state)
      && (flow.reportVersion === version || flow.state === 'returned');
    const status = current ? flow.state : 'draft';
    return {store, report, flow, version, status, token: JSON.stringify([version, flow?.revision ?? 0, status])};
  }

  function editorIsDirty() {
    const input = document.querySelector('[data-demo-conclusion]');
    return input && !input.closest('[hidden]') && input.value !== viewedConclusion;
  }

  function renderDesk(message = '', preserveInput = false) {
    try {
      const {report, flow, status, token, version} = readWorkspace();
      if (preserveInput && viewed !== token && editorIsDirty()) {
        showError('报告在其他标签页中已更新。当前输入已保留，请刷新核对后再保存。');
        return;
      }
      if (preserveInput && viewed === token) return;
      viewed = token;
      viewedConclusion = typeof report?.conclusion === 'string' ? report.conclusion : '';
      const put = (selector, value) => document.querySelectorAll(selector).forEach(node => { node.textContent = value; });
      const stage = status === 'returned' ? 'draft' : status;
      put('[data-demo-case-status], [data-demo-report-status]', labels[status]);
      put('[data-demo-return-detail]', status === 'returned' ? flow.reason : '');
      const feedbackNotice = document.querySelector('[data-demo-feedback]');
      feedbackNotice.textContent = message;
      feedbackNotice.hidden = !message;
      document.querySelector('[data-demo-error]').hidden = true;
      document.querySelectorAll('[data-demo-states]').forEach(section => {
        section.hidden = !section.dataset.demoStates.split(/\s+/).includes(status);
      });
      document.querySelectorAll('[data-demo-stage]').forEach(node => {
        if (node.dataset.demoStage === stage) node.setAttribute('aria-current', 'step');
        else node.removeAttribute('aria-current');
      });
      const input = document.querySelector('[data-demo-conclusion]');
      if (input) input.value = viewedConclusion;
      const reason = document.querySelector('[data-demo-return-reason]');
      if (reason) reason.value = '';
      put('[data-demo-report-conclusion]', viewedConclusion || '尚无报告结论');
      put('[data-demo-report-version]', String(version));
      const count = Array.isArray(report?.composition?.selected_events) ? report.composition.selected_events.length : 0;
      put('[data-demo-report-strips]', `${count} 张`);
      const time = document.querySelector('[data-demo-report-date]');
      const timestamp = typeof report?.updated_at === 'string' ? Date.parse(report.updated_at) : NaN;
      if (time) time.closest('[data-demo-report-date-row]').hidden = !Number.isFinite(timestamp);
      if (time && Number.isFinite(timestamp)) {
        time.dateTime = new Date(timestamp).toISOString();
        time.textContent = new Intl.DateTimeFormat('zh-CN', {dateStyle: 'medium', timeStyle: 'short'}).format(timestamp);
      }
    } catch {
      showError('无法读取浏览器中的演示报告。请检查站点存储设置。');
    }
  }

  function handleAction(action) {
    try {
      const {store, report, flow, version, status, token} = readWorkspace();
      if (token !== viewed) throw Error('报告版本已变化，请重新打开后核对。');
      if (!allowed[page]?.[status]?.includes(action)) throw Error('当前报告状态下无法执行此操作。');
      const next = {state: status, reportVersion: version, revision: (flow?.revision ?? 0) + 1};
      if (action === 'save' || action === 'submit') {
        const conclusion = document.querySelector('[data-demo-conclusion]').value;
        if (action === 'submit' && !conclusion.trim()) throw Error('请填写演示报告结论后再提交审核。');
        if (conclusion.length > 12000) throw Error('报告结论最多 12000 字。');
        next.reportVersion++;
        const reports = store.reports ||= {};
        reports[caseId] = {...report, conclusion, status: 'draft', version: next.reportVersion, updated_at: new Date().toISOString()};
        if (action === 'submit') next.state = 'pending';
        else if (status === 'returned') next.reason = flow.reason;
      } else if (action === 'return') {
        const reason = document.querySelector('[data-demo-return-reason]').value.trim();
        if (!reason || reason.length > 500) throw Error('请填写退回原因，最多 500 字。');
        next.state = 'returned';
        next.reason = reason;
      } else {
        next.state = action === 'approve' ? 'approved' : 'draft';
      }
      (store.demoHandoff ||= {})[caseId] = next;
      localStorage.setItem(workspaceKey(), JSON.stringify(store));
      renderDesk(feedback[action]);
    } catch (error) {
      showError(error.name === 'QuotaExceededError' || error.name === 'SecurityError'
        ? '浏览器无法保存修改。请检查站点存储设置。' : error.message);
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
    const worklist = document.createElement('button');
    worklist.type = 'button';
    worklist.dataset.demoDesk = '';
    worklist.textContent = '返回诊断工作台';
    const logout = document.createElement('button');
    logout.type = 'button';
    logout.dataset.demoLogout = '';
    logout.textContent = '退出登录';
    host.replaceChildren(worklist, logout);
    const view = new URLSearchParams(location.search).get('view');
    if (view === 'review' || view === 'report') window.addEventListener('load', () => {
      if (typeof selectCase !== 'function') return;
      // Case selection cancels in-flight reads. Let the shared index finish first.
      const open = () => {
        if (allowWorkbench() && !state.caseId) selectCase(caseId, view).catch(handleError);
      };
      const status = document.getElementById('caseIndexStatus');
      if (state.dashboardStatus !== 'loading' || !status) {
        open();
        return;
      }
      const observer = new MutationObserver(() => {
        if (state.dashboardStatus === 'loading') return;
        observer.disconnect();
        open();
      });
      observer.observe(status, {childList: true, characterData: true, subtree: true});
    }, {once: true});
  }

  function bind() {
    if (!guardRole()) return;
    if (page === 'workbench') mountWorkbenchAccount();
    if (desk) {
      renderDesk();
      window.addEventListener('storage', event => {
        if (!event.key || event.key === workspaceKey()) renderDesk('', true);
      });
    }

    document.addEventListener('click', event => {
      if (desk && event.target.closest('a[href^="workbench.html"]') && editorIsDirty()
          && !window.confirm('诊断结论尚未保存，仍然离开吗？')) {
        event.preventDefault();
        return;
      }
      const button = event.target.closest('button[data-demo-role], button[data-demo-logout], button[data-demo-desk], button[data-demo-workflow-action]');
      if (!button || button.disabled || !guardRole()) return;
      if (button.dataset.demoWorkflowAction) {
        handleAction(button.dataset.demoWorkflowAction);
        return;
      }
      const role = button.dataset.demoRole;
      if (role && !Object.hasOwn(destinations, role)) return;
      if (page === 'workbench' && typeof clinicalWorkflow !== 'undefined' && !clinicalWorkflow.allowLeave()) return;
      if (desk && editorIsDirty() && !window.confirm('诊断结论尚未保存，仍然离开吗？')) return;
      if ('demoDesk' in button.dataset) {
        location.assign(destinations.diagnosis);
        return;
      }
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

  if (page === 'workbench' && !allowWorkbench()) {
    // Navigation may complete after parsing. Avoid starting shared reads in the meantime.
    document.addEventListener('DOMContentLoaded', event => event.stopImmediatePropagation(), {capture: true, once: true});
    return;
  }
  if (!guardRole()) return;
  document.addEventListener('DOMContentLoaded', bind, {once: true});
  window.addEventListener('pageshow', event => {
    if (!event.persisted) return;
    if (page === 'workbench') allowWorkbench();
    else if (guardRole() && desk) renderDesk('', true);
  });
})();
