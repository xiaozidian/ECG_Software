'use strict';

// Browser transport for the shared account-trial portal. The public site uses
// one mathematical case and demonstration identities, with no account server.
(() => {
  const root = document.documentElement;
  const page = root.dataset.demoPortalPage;
  const site = new URL('../../', document.currentScript.src);
  const loginUrl = new URL('index.html', site).href;
  const stateUrl = new URL('trial/state', site).href;
  const roleKey = 'cardioinsight.demo.portal.role';
  const previousStorageKey = 'cardioinsight.math.dba35ed796dda93c5de4710679d0a6bb6375c678a284ed7ab41e3f79e006e356';
  const cases = {id: 'math-4314-001', label: 'M01'};
  const accounts = {
    diag01: {role: 'diagnosis', name: '诊断医生（测试）', label: '诊断医生', password: 'diag-preview'},
    review01: {role: 'review', name: '审核医生（测试）', label: '审核医生', password: 'review-preview'},
  };
  const pages = {diagnosis: 'diagnosis.html', review: 'review.html'};
  const allowed = {diagnosis: ['save', 'submit', 'withdraw', 'amend'], review: ['return', 'sign']};
  const states = {draft: '诊断草稿', pending: '待审核', returned: '退回修改', withdrawn: '已撤回', signed: '已测试签发'};
  const actions = {save: '保存诊断草稿', submit: '提交审核', withdraw: '撤回送审', amend: '从已签版新建更正稿',
    return: '退回修改', sign: '个人测试签章并验签'};
  const evidenceFields = ['annotations', 'templates', 'beatOverrides', 'reviews', 'evidenceCandidates',
    'evidenceReviews', 'sttRecordBindings'];
  const evidenceDocuments = ['beatEditor', 'rhythms', 'hrvReviews'];
  const testPin = '135790';
  const readOnlyFetch = window.fetch.bind(window);
  const dateFormat = new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Shanghai', month: '2-digit',
    day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'});

  function storageKey() {
    const fingerprint = window.__CARDIOINSIGHT_SOURCE_VERSION__?.source_fingerprint;
    return window.ECGDemoTrialStorageKey
      || (fingerprint ? `cardioinsight.math.${fingerprint}` : 'cardioinsight-public-math-4314-v2');
  }

  function currentRole() {
    try {
      const role = sessionStorage.getItem(roleKey);
      return Object.hasOwn(pages, role) ? role : null;
    } catch {
      return null;
    }
  }

  function deskUrl(role = currentRole()) {
    return role ? new URL(pages[role], site).href : loginUrl;
  }

  function pastSubmission(round, kind = 'preview') {
    const row = readWorkspace().flow.history.find(item => item.round_no === round);
    if (!row || (kind === 'signed' && row.state !== 'signed')) return null;
    return row;
  }

  function signaturePayload(row) {
    return new TextEncoder().encode(JSON.stringify([cases.id, row.round_no, row.author, row.reviewer,
      row.submitted, row.clinical_version, row.conclusion, row.composition, row.evidence, row.signed_at]));
  }

  async function verifySubmission(row) {
    const record = row?.test_signature;
    if (!record) return false;
    const key = await crypto.subtle.importKey('jwk', record.public_key, {name: 'ECDSA', namedCurve: 'P-256'},
      false, ['verify']);
    return crypto.subtle.verify({name: 'ECDSA', hash: 'SHA-256'}, key,
      Uint8Array.from(atob(record.signature), char => char.charCodeAt(0)), signaturePayload(row));
  }

  async function signSubmission(row) {
    const key = await crypto.subtle.generateKey({name: 'ECDSA', namedCurve: 'P-256'}, false, ['sign', 'verify']);
    const signed = await crypto.subtle.sign({name: 'ECDSA', hash: 'SHA-256'}, key.privateKey, signaturePayload(row));
    row.test_signature = {public_key: await crypto.subtle.exportKey('jwk', key.publicKey),
      signature: btoa(String.fromCharCode(...new Uint8Array(signed)))};
    if (!await verifySubmission(row)) throw new Error('演示签名校验失败。');
  }

  function freezeEvidence(store) {
    const evidence = {};
    for (const field of evidenceFields) {
      if (store[field]?.[cases.id] !== undefined) evidence[field] = {[cases.id]: store[field][cases.id]};
    }
    for (const field of evidenceDocuments) {
      const current = store[field]?.[cases.id];
      if (current) evidence[field] = {[cases.id]: {...current, undo: [], redo: []}};
    }
    if (store.terminologyCatalogs) evidence.terminologyCatalogs = store.terminologyCatalogs;
    return structuredClone(evidence);
  }

  function reportUrl(round, kind = 'preview') {
    return `workbench.html?view=report&round=${round}&kind=${kind}`;
  }

  function formatTime(value) {
    const time = new Date(value || NaN);
    if (Number.isNaN(time.valueOf())) return '—';
    const parts = Object.fromEntries(dateFormat.formatToParts(time).map(part => [part.type, part.value]));
    return `${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
  }

  function importEarlierFlow(legacy, report, version) {
    const state = legacy?.state === 'approved' ? 'signed' : legacy?.state;
    const record = state === 'returned' || (state === 'pending' || state === 'signed') && legacy.reportVersion === version;
    if (!record) return {state: 'draft', revision: legacy?.revision || 0, active: null, history: [], events: []};
    const submitted = report?.updated_at || new Date().toISOString();
    const entry = {id: 1, round_no: 1, author: 'diag01', reviewer: 'review01', submitted,
      clinical_version: version, conclusion: report?.conclusion || '', composition: report?.composition || {},
      state, reason: legacy.reason || '', signed_at: state === 'signed' ? submitted : ''};
    return {state, revision: legacy.revision || 1, active: entry.id, reportVersion: version, history: [entry],
      events: [{actor: 'diag01', at: submitted, action: actions.submit, submission: entry.id}]};
  }

  function readWorkspace() {
    const store = JSON.parse(localStorage.getItem(storageKey()) || '{}');
    if (!store || typeof store !== 'object' || Array.isArray(store)) throw new Error('无法读取浏览器中的演示报告。');
    const report = store.reports?.[cases.id];
    const version = Number.isSafeInteger(report?.version) ? report.version : 1;
    const reviewRevision = store.reviews?.[cases.id]?.revision ?? 0;
    const flow = store.demoTrialWorkflow?.[cases.id] || importEarlierFlow(store.demoHandoff?.[cases.id], report, version);
    const active = flow.history.find(row => row.id === flow.active);
    const status = flow.state;
    return {store, report, flow, active, version, reviewRevision, status,
      token: JSON.stringify([version, reviewRevision, flow.revision, status])};
  }

  function addCell(row, text) {
    const cell = row.insertCell();
    cell.textContent = text;
    return cell;
  }

  function reportLink(doc, round, kind, label, download = false) {
    const link = doc.createElement('a');
    link.href = reportUrl(round, kind) + (download ? '&download=1' : '');
    if (!download) {
      link.target = '_blank';
      link.rel = 'opener';
    }
    link.textContent = label;
    return link;
  }

  function renderHistory(doc, history) {
    const table = doc.querySelector('.history-panel tbody');
    if (!table) return;
    table.replaceChildren();
    for (const item of history) {
      const row = table.insertRow();
      addCell(row, `第 ${item.round_no} 次`);
      addCell(row, formatTime(item.submitted));
      const details = addCell(row, states[item.state]);
      if (item.reason) {
        const reason = doc.createElement('small');
        reason.textContent = item.reason;
        details.append(reason);
      }
      const files = addCell(row, '');
      files.append(reportLink(doc, item.round_no, 'preview', '送审稿'));
      if (item.signed_at) files.append(' · ', reportLink(doc, item.round_no, 'signed', '已签版'));
    }
  }

  function renderActivity(doc, events) {
    const list = doc.querySelector('.activity-list');
    if (!list) return;
    list.replaceChildren();
    if (!events.length) {
      const item = doc.createElement('li');
      const time = doc.createElement('span');
      time.textContent = '本例尚无交接记录';
      item.append(time);
      list.append(item);
      return;
    }
    for (const event of events.slice(0, 8)) {
      const item = doc.createElement('li');
      const action = doc.createElement('strong');
      const time = doc.createElement('span');
      action.textContent = event.action;
      time.textContent = `${accounts[event.actor]?.label || '演示账号'} · ${formatTime(event.at)}`;
      item.append(action, time);
      list.append(item);
    }
  }

  function layoutFor(role) {
    const snapshot = readWorkspace();
    const {active, flow, report, status, version, reviewRevision} = snapshot;
    const variant = status === 'draft' && !flow.history.length ? 'empty' : status;
    const template = window.ECGDemoTrialLayouts?.[role]?.[variant];
    if (typeof template !== 'string') throw new Error('演示工作台尚未加载，请刷新页面。');
    const values = {
      DEMO_QUEUE_REVISION: flow.revision, DEMO_REVISION: flow.revision,
      DEMO_CONCLUSION: active && (status === 'pending' || status === 'signed') ? active.conclusion : report?.conclusion || '',
      DEMO_REPORT_VERSION: version, DEMO_REVIEW_REVISION: reviewRevision,
      DEMO_ROUND: active?.round_no ?? 0, DEMO_SUBMISSION_ID: active?.id ?? 0,
      DEMO_SUBMITTED: formatTime(active?.submitted), DEMO_SIGNED_AT: formatTime(active?.signed_at),
      DEMO_RETURN_REASON: active?.reason || '', DEMO_EVENT_ACTION: '', DEMO_EVENT_AT: '',
    };
    const entities = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'};
    const html = template.replace(/DEMO_[A-Z_]+/g, token => Object.hasOwn(values, token)
      ? String(values[token]).replace(/[&<>"']/g, char => entities[char]) : token);
    const doc = new DOMParser().parseFromString(html, 'text/html');
    renderHistory(doc, flow.history);
    renderActivity(doc, flow.events);
    // Both local and static builds use the exact report-link markup. Resolve
    // those links to the published mathematical workbench on this host.
    for (const link of doc.querySelectorAll('a[href]')) {
      const match = link.getAttribute('href').match(/\/report\/(\d+)\/(preview|signed)\.pdf(\?download=1)?$/);
      if (match) link.setAttribute('href', reportUrl(Number(match[1]), match[2]) + (match[3] ? '&download=1' : ''));
    }
    return doc;
  }

  function mount() {
    const role = currentRole();
    if (page === 'workbench') return true;
    if (page === 'login') {
      if (!role) return true;
      location.replace(deskUrl(role));
      return false;
    }
    if (role !== page) {
      location.replace(deskUrl(role));
      return false;
    }
    try {
      const doc = layoutFor(role);
      document.title = doc.title;
      document.body.replaceChildren(...doc.body.childNodes);
      return true;
    } catch (error) {
      const status = document.querySelector('.global-error');
      if (status) status.textContent = error.message;
      return false;
    }
  }

  const json = (value, status = 200) => Response.json(value, {status, headers: {'Cache-Control': 'no-store'}});
  const failure = (error, status) => json({error}, status);
  const int = (form, name) => {
    const value = form.get(name);
    return typeof value === 'string' && /^\d+$/.test(value) ? Number(value) : -1;
  };

  async function act(role, action, form) {
    if (!allowed[role]?.includes(action)) return failure('当前岗位不能执行此操作。', 403);
    const {store, report, flow, active, version, reviewRevision, status, token} = readWorkspace();
    const expected = int(form, 'revision');
    const submission = int(form, 'submission');
    if (action === 'sign' && status === 'signed' && active?.id === submission && expected === flow.revision - 1) {
      return json({next: deskUrl(role)});
    }
    if (expected !== flow.revision) return failure('另一窗口已更新此报告，请刷新查看当前版本。', 409);
    const actor = role === 'diagnosis' ? 'diag01' : 'review01';
    const at = new Date().toISOString();
    if (action === 'save' || action === 'submit') {
      if (!['draft', 'returned'].includes(status)) return failure('该版本已送审，请先撤回或新建更正稿。', 409);
      if (int(form, 'clinical_version') !== version || int(form, 'review_revision') !== reviewRevision) {
        return failure('工作站中的报告或证据已更新，请刷新后核对。', 409);
      }
      const conclusion = String(form.get('conclusion') || '').trim();
      if (!conclusion || conclusion.length > 12000) return failure('请填写 1 至 12000 字的诊断结论。', 400);
      const draft = action === 'submit' && report?.conclusion === conclusion
        ? report : {...report, status: 'draft', version: version + 1, conclusion, updated_at: at};
      (store.reports ||= {})[cases.id] = draft;
      if (action === 'submit') {
        const round = (flow.history[0]?.round_no || 0) + 1;
        flow.active = round;
        flow.state = 'pending';
        flow.reportVersion = draft.version;
        flow.history.unshift({id: round, round_no: round, author: actor, reviewer: 'review01', submitted: at,
          clinical_version: draft.version, conclusion, composition: structuredClone(draft.composition || {}),
          evidence: freezeEvidence(store), state: 'pending', reason: '', signed_at: ''});
      }
    } else if (action === 'amend') {
      if (status !== 'signed') return failure('当前报告尚未签发。', 409);
      flow.state = 'draft';
    } else {
      if (status !== 'pending' || active?.id !== submission) return failure('此送审批次已变化，请刷新。', 409);
      if (action === 'return') {
        const reason = String(form.get('reason') || '').trim();
        if (!reason || reason.length > 500) return failure('请填写 1 至 500 字的退回原因。', 400);
        active.state = flow.state = 'returned';
        active.reason = reason;
      } else if (action === 'withdraw') {
        active.state = 'withdrawn';
        flow.state = 'draft';
      } else {
        if (form.get('pin') !== testPin) return failure('测试签章口令有误，报告仍待审核。', 403);
        active.state = flow.state = 'signed';
        active.signed_at = at;
        await signSubmission(active);
        if (readWorkspace().token !== token) {
          return failure('签发期间此送审批次已变化，请刷新。', 409);
        }
      }
    }
    flow.revision++;
    flow.events.unshift({actor, at, action: actions[action], submission: flow.active});
    flow.events = flow.events.slice(0, 8);
    (store.demoTrialWorkflow ||= {})[cases.id] = flow;
    localStorage.setItem(storageKey(), JSON.stringify(store));
    return json({next: deskUrl(role)});
  }

  async function request(input, init = {}) {
    const url = new URL(input instanceof Request ? input.url : input, location.href);
    const method = String(init.method || (input instanceof Request && input.method) || 'GET').toUpperCase();
    const path = url.pathname;
    const relative = path.startsWith(site.pathname) ? path.slice(site.pathname.length) : '';
    const trialPath = path.startsWith('/trial/') ? path : relative.startsWith('trial/') ? '/' + relative : '';
    const deskPage = Object.values(pages).includes(relative);
    const deskAction = relative.match(/^(diagnosis|review)\.html\/action\/(\w+)$/);
    if (url.origin !== site.origin || (!trialPath && !deskPage && !deskAction)) return readOnlyFetch(input, init);
    const role = currentRole();
    try {
      if (method === 'GET' && trialPath === '/trial/state') {
        return role ? json({revision: readWorkspace().flow.revision}) : failure('请先登录验证工作区。', 401);
      }
      if (method === 'GET' && (deskPage || trialPath === `/trial/cases/${cases.label}`)) {
        if (!role) return failure('请先登录验证工作区。', 401);
        const doc = layoutFor(role);
        return new Response('<!doctype html>' + doc.documentElement.outerHTML,
          {headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'}});
      }
      if (method === 'POST' && trialPath === '/trial/login') {
        const form = init.body;
        const id = form.get('account');
        if (!Object.hasOwn(accounts, id) || form.get('password') !== accounts[id].password) {
          return failure('工号或口令有误，请重新输入。', 401);
        }
        const nextRole = accounts[id].role;
        sessionStorage.setItem(roleKey, nextRole);
        return json({next: deskUrl(nextRole), identity_changed: true});
      }
      if (method === 'POST' && trialPath === '/trial/logout') {
        sessionStorage.removeItem(roleKey);
        return json({next: loginUrl, identity_changed: true});
      }
      const action = trialPath.match(/^\/trial\/cases\/M01\/action\/(\w+)$/)?.[1] || deskAction?.[2];
      if (method !== 'POST' || !action) return failure('未找到演示操作。', 404);
      if (!role) return failure('请先登录验证工作区。', 401);
      if (deskAction && deskAction[1] !== role) return failure('当前岗位不能执行此操作。', 403);
      const run = () => act(role, action, init.body);
      return globalThis.navigator.locks ? await navigator.locks.request(storageKey(), run) : await run();
    } catch {
      return failure('浏览器无法读写演示记录。请检查站点存储设置后重试。', 500);
    }
  }

  try {
    if (localStorage.getItem(storageKey()) === null) {
      const previous = localStorage.getItem(previousStorageKey);
      const decoded = JSON.parse(previous);
      if (decoded && typeof decoded === 'object' && !Array.isArray(decoded)) {
        localStorage.setItem(storageKey(), previous);
      }
    }
  } catch { /* Preserve the previous version. The normal workflow reports storage access errors. */ }

  window.ECGDemoTrial = {request, mount, loginUrl, stateUrl, deskUrl, currentRole, readWorkspace, pastSubmission,
    verifySubmission, storageKey};
})();
