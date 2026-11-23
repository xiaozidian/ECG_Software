(() => {
  'use strict';
  const token = document.querySelector('meta[name="trial-token"]').content;
  const identityKey = 'ecg-trial-identity';
  const html = document.documentElement;
  const fetchOriginal = window.fetch.bind(window);
  const localWrite = {'X-Trial-Token': token, 'X-CardioInsight-Request': '1'};
  const epoch = document.querySelector('meta[name="trial-workspace"]')?.content;
  if (epoch) localWrite['X-CardioInsight-Workspace'] = epoch;
  let navigating = false;

  // Apply the login nonce to the existing clinical client's own requests, preserving its headers and body.
  if (html.hasAttribute('data-account-trial')) {
    window.fetch = (input, init = {}) => {
      const url = new URL(input instanceof Request ? input.url : input, location.href);
      const method = init.method || (input instanceof Request ? input.method : 'GET');
      if (url.origin === location.origin && !['GET','HEAD','OPTIONS'].includes(method.toUpperCase())) {
        const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
        headers.set('X-Trial-Token', token);
        if (epoch && !headers.has('X-CardioInsight-Workspace')) headers.set('X-CardioInsight-Workspace', epoch);
        return fetchOriginal(input, {...init, headers});
      }
      return fetchOriginal(input, init);
    };
  }

  function identityChanged() {
    // The localhost origin is exclusively the account rehearsal.
    for (const key of Object.keys(localStorage)) {
      if (key !== identityKey) localStorage.removeItem(key);
    }
    sessionStorage.clear();
    localStorage.setItem(identityKey, crypto.randomUUID());
  }
  window.addEventListener('storage', event => {
    if (event.key === identityKey) {
      sessionStorage.clear();
      location.replace(location.pathname.startsWith('/trial/cases/') ? location.pathname :
        document.querySelector('[data-trial-leave]')?.href || '/trial/');
    }
  });
  window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });

  function draftChanged() {
    const field = document.getElementById('conclusion');
    return field && field.value !== field.defaultValue;
  }
  window.addEventListener('beforeunload', event => {
    if (!navigating && draftChanged()) { event.preventDefault(); event.returnValue = ''; }
  });

  function bindPortal() {
    let busy = false, polling = false, pendingRefresh = false, refreshSequence = 0;
    const status = document.querySelector('[data-workflow-status]');
    const desk = document.querySelector('.desk');
    const visibleStatus = message => { if (status) status.textContent = message; };

    function replaceSection(selector, next) {
      const old = document.querySelector(selector), fresh = next.querySelector(selector);
      if (old && fresh) old.replaceWith(fresh);
      else if (old) old.remove();
      else if (fresh) document.querySelector('.desk-footer').before(fresh);
    }
    async function updateDesk(url, {save = false, savedConclusion = '', poll = false} = {}) {
      const sequence = ++refreshSequence;
      const response = await fetchOriginal(url, {cache:'no-store'});
      if (sequence !== refreshSequence) return;
      if (response.status === 401 || new URL(response.url).pathname === '/trial/login') {
        navigating = true; location.replace('/trial/login'); return;
      }
      if (!response.ok) throw new Error('暂时无法更新工作台。');
      const next = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (sequence !== refreshSequence) return;
      const fresh = next.querySelector('.desk');
      if (!desk || !fresh || next.querySelector('meta[name="trial-token"]')?.content !== token) {
        navigating = true; location.assign(url); return;
      }
      if (poll && (busy || document.querySelector('dialog[open]'))) return;
      replaceSection('.case-picker', next);
      const sameCase = desk.dataset.case === fresh.dataset.case;
      const unchanged = sameCase && desk.dataset.caseRevision === fresh.dataset.caseRevision;
      if (poll && sameCase && draftChanged() && !unchanged) {
        desk.dataset.revision = fresh.dataset.revision;
        pendingRefresh = true;
        visibleStatus('本例在另一窗口已有更新。当前输入已保留。');
        const refresh = document.querySelector('[data-refresh-workflow]'); if (refresh) refresh.hidden = false;
        return;
      }
      if (!poll || !unchanged) {
        const editor = document.getElementById('conclusion');
        if (save && editor && next.getElementById('conclusion')) {
          for (const input of document.querySelectorAll('#draft-form input[type=hidden]')) {
            const field = next.querySelector('#draft-form input[name="' + input.name + '"]');
            if (field) input.value = field.value;
          }
          const currentText = editor.value;
          editor.defaultValue = savedConclusion;
          if (editor.value !== currentText) editor.value = currentText;
          replaceSection('.activity-panel', next);
        } else {
          replaceSection('.desk-columns', next);
        }
        replaceSection('.history-panel', next);
        for (const dialog of document.querySelectorAll('.account-portal > dialog')) dialog.remove();
        for (const dialog of next.querySelectorAll('.account-portal > dialog')) document.body.append(dialog);
      }
      desk.dataset.revision = fresh.dataset.revision;
      desk.dataset.caseRevision = fresh.dataset.caseRevision;
      desk.dataset.case = fresh.dataset.case;
      pendingRefresh = false;
      const refresh = document.querySelector('[data-refresh-workflow]'); if (refresh) refresh.hidden = true;
      if (!poll) visibleStatus(save ? (draftChanged() ? '草稿已保存，新输入待保存' : '草稿已保存') : '操作已完成');
    }

    async function checkQueue() {
      if (!desk || polling || busy || navigating || document.hidden || document.querySelector('dialog[open]')) return;
      polling = true;
      try {
        const response = await fetchOriginal('/trial/state', {cache:'no-store'});
        if (response.status === 401) { navigating = true; location.replace('/trial/login'); return; }
        if (response.ok && (await response.json()).revision !== Number(desk.dataset.revision) && !busy && !navigating) {
          await updateDesk(location.href, {poll:true});
        }
      } catch { /* The current case and any unsaved conclusion remain available. */ }
      finally { polling = false; }
    }
    if (desk) {
      window.addEventListener('focus', checkQueue);
      window.setInterval(checkQueue, 5000);
    }
    document.addEventListener('click', async event => {
      const button = event.target.closest('button');
      if (!button || button.disabled) return;
      if (button.dataset.loginAs) {
        const login = document.getElementById('login-form');
        login.elements.account.value = button.dataset.loginAs;
        login.elements.password.value = button.dataset.demoPassword;
        login.requestSubmit();
      } else if (button.dataset.open) {
        const dialog = document.getElementById(button.dataset.open);
        dialog.showModal();
        dialog.querySelector('input:not([type=hidden]),textarea')?.focus();
      } else if (button.hasAttribute('data-close')) {
        button.closest('dialog').close();
        checkQueue();
      } else if (button.hasAttribute('data-refresh-workflow')) {
        if (pendingRefresh && draftChanged() && !window.confirm('本例已有新版本。放弃当前未保存的文字并查看新版本？')) return;
        try { await updateDesk(location.href); }
        catch { visibleStatus('更新失败，请重试。'); }
      }
    });
    document.addEventListener('submit', async event => {
      const form = event.target;
      event.preventDefault();
      if (busy) return;
      const path = event.submitter?.getAttribute('formaction') || form.action;
      const action = new URL(path, location.href).pathname.split('/').at(-1);
      if ((form.hasAttribute('data-switch') || action === 'logout') && draftChanged() &&
          !window.confirm('诊断结论尚未保存。放弃这次修改并切换账号？')) return;
      const errorBox = form.querySelector('.form-error') || document.querySelector('.global-error');
      if (errorBox) errorBox.textContent = '';
      const payload = new FormData(form), submitter = event.submitter;
      const originalLabel = submitter?.textContent;
      const buttons = [...document.querySelectorAll('button:not(:disabled)')];
      const fields = action === 'save' ? [] : [...form.querySelectorAll('input:not([type=hidden]),textarea')].filter(field => !field.readOnly);
      busy = true;
      refreshSequence++;
      buttons.forEach(button => { button.disabled = true; });
      fields.forEach(field => { field.readOnly = true; });
      const messages = {submit:'正在生成送审稿…', sign:'正在签发并验签…', save:'正在保存草稿…', return:'正在退回…', withdraw:'正在撤回…', amend:'正在创建更正稿…'};
      const message = messages[action] || '正在处理…';
      visibleStatus(message);
      if (submitter) submitter.textContent = message;
      form.setAttribute('aria-busy','true');
      try {
        const response = await fetchOriginal(path, {method:'POST', headers:localWrite, body:payload});
        const result = await response.json();
        if (!response.ok) {
          if (response.status === 409) {
            pendingRefresh = true;
            const refresh = document.querySelector('[data-refresh-workflow]'); if (refresh) refresh.hidden = false;
          }
          throw new Error(result.error || '操作未完成，请重试。');
        }
        if (result.identity_changed) {
          navigating = true; identityChanged(); location.assign(result.next); return;
        }
        // The server has already committed the action. A display failure must never submit it twice.
        try { await updateDesk(result.next, {save:action === 'save', savedConclusion:payload.get('conclusion') || ''}); }
        catch { navigating = true; location.assign(result.next); }
      } catch (error) {
        if (errorBox) { errorBox.textContent = error.message || '连接中断，请重试。'; errorBox.scrollIntoView({block:'nearest'}); }
        visibleStatus('操作尚未完成');
      } finally {
        if (!navigating) {
          for (const button of buttons) if (button.isConnected) button.disabled = false;
          for (const field of fields) if (field.isConnected) field.readOnly = false;
          if (submitter?.isConnected) submitter.textContent = originalLabel;
          form.removeAttribute('aria-busy');
          busy = false;
        }
      }
    });
  }

  function bindClinical() {
    const deskLink = document.querySelector('[data-trial-leave]');
    const submit = document.createElement('a');
    submit.textContent = '提交审核';
    submit.className = 'button primary';
    submit.href = deskLink.href;
    submit.setAttribute('data-trial-leave','');
    document.getElementById('saveReport')?.after(submit);
    function syncDeskLinks() {
      const activeCase = state.caseData?.case_id === state.caseId ? state.caseData :
        state.cases?.find(item => item.case_id === state.caseId);
      if (/^C\d{2,}$/.test(activeCase?.display_case_id)) {
        deskLink.href = submit.href = '/trial/cases/' + activeCase.display_case_id;
      }
    }
    // The native patient list can also change the selected case inside this page.
    new MutationObserver(syncDeskLinks).observe(document.getElementById('reportCaseLabel'), {childList:true});
    document.querySelectorAll('[data-trial-leave]').forEach(link => link.addEventListener('click', async event => {
      syncDeskLinks();
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      if (!await resolveWorkstationLeave()) return;
      if (typeof clinicalUI !== 'undefined' && !await clinicalUI.resolveReportLeave()) return;
      location.assign(link.href);
    }));
  }
  document.addEventListener('DOMContentLoaded', () => {
    if (html.hasAttribute('data-account-trial')) bindClinical();
    else bindPortal();
  });
})();
