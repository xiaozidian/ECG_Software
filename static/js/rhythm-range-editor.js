"use strict";
/* Manual, sample-grid AF ranges. This module neither detects rhythm nor edits QRS. */
(function (root) {
  const clone = value => JSON.parse(JSON.stringify(value));
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const integer = value => Number.isSafeInteger(value) && value >= 0;
  const scopeKeys = ['case_id', 'caseToken', 'analysis_basis', 'analysis_revision', 'beat_revision', 'workspace_epoch'];
  const sourceKeys = ['case_id', 'analysis_basis', 'beat_revision'];
  const identityKeys = ['case_id', 'analysis_basis', 'analysis_revision', 'beat_revision'];
  const statusName = value => ({pending: '待复核', confirmed: '医生确认', excluded: '已排除'})[value] || value;
  function scope(value) {
    if (!value || typeof value.case_id !== 'string' || !value.case_id ||
        !['string', 'number'].includes(typeof value.caseToken) ||
        typeof value.analysis_basis !== 'string' || !value.analysis_basis ||
        !integer(value.analysis_revision) || !integer(value.beat_revision) ||
        !finite(value.duration_s) || value.duration_s <= 0 || value.sample_rate_hz !== 200)
      throw Error('病例、波形依据或 200 Hz 原始采样范围尚未就绪');
    const samples = Math.round(value.duration_s * value.sample_rate_hz);
    if (!integer(samples) || samples < 1 || Math.abs(samples - value.duration_s * 200) > 1e-5)
      throw Error('原始记录长度不在采样网格上');
    return {...Object.fromEntries(scopeKeys.map(k => [k, value[k] ?? null])),
      duration_s: value.duration_s, sample_rate_hz: 200, sample_count: samples};
  }
  function same(a, b, keys = scopeKeys) {
    return !!a && !!b && keys.every(k => (a[k] ?? null) === (b[k] ?? null));
  }
  function identity(value) {
    if (!value || typeof value.case_id !== 'string' || typeof value.analysis_basis !== 'string' ||
        !integer(value.analysis_revision) || !integer(value.beat_revision))
      throw Error('片段响应缺少完整病例或修订依据，请重新读取核对');
    return Object.fromEntries(identityKeys.map(k => [k, value[k]]));
  }
  function currentSurface(s, surface) {
    return !!surface && same(s, surface.owner_scope) &&
      finite(surface.wave?.start_s) && finite(surface.wave?.duration_s) && surface.wave.duration_s > 0 &&
      surface.wave.start_s >= 0 && surface.wave.start_s + surface.wave.duration_s <= s.duration_s + 1e-6 &&
      finite(surface.plot?.left) && finite(surface.plot?.top) &&
      finite(surface.plot?.width) && surface.plot.width > 0 && finite(surface.plot?.height) && surface.plot.height > 0;
  }
  function pointerSample(s, surface, localX) {
    if (!currentSurface(s, surface)) throw Error('当前波形与病例依据不同，不能设置片段边界');
    if (!finite(localX) || localX < surface.plot.left || localX > surface.plot.left + surface.plot.width)
      throw Error('请在连续波形绘图区内选择边界');
    const fraction = (localX - surface.plot.left) / surface.plot.width;
    return Math.min(s.sample_count, Math.max(0, Math.round((surface.wave.start_s + fraction * surface.wave.duration_s) * s.sample_rate_hz)));
  }
  function secondsSample(text, s) {
    if (typeof text !== 'string' || !text.trim()) throw Error('请输入片段边界秒数');
    const seconds = Number(text), sample = Math.round(seconds * s.sample_rate_hz);
    if (!finite(seconds) || seconds < 0 || seconds > s.duration_s || Math.abs(seconds * 200 - sample) > 1e-5)
      throw Error('边界必须位于记录内的 0.005 秒原始采样网格');
    return sample;
  }
  function range(start, end, s) {
    if (!integer(start) || !integer(end) || !(start < end) || start >= s.sample_count || end > s.sample_count)
      throw Error('请先选择起点与更晚的终点；起点包含，终点不包含');
    return {start_sample: start, end_sample_exclusive: end, start_s: start / 200, end_s: end / 200};
  }
  function episode(draft) {
    const bounds = range(draft.start_sample, draft.end_sample_exclusive, draft.scope);
    if (!['pending', 'confirmed'].includes(draft.status)) throw Error('请选择待复核或医生确认状态');
    return {id: draft.id, start_s: bounds.start_s, end_s: bounds.end_s, kind: 'AF',
      status: draft.status, source: 'manual', note: String(draft.note || '').slice(0, 1000)};
  }
  function overlaps(item, document) {
    return (document?.episodes || []).filter(x => x.id !== item.id && x.start_s < item.end_s && item.start_s < x.end_s)
      .map(x => ({id: x.id, start_s: x.start_s, end_s: x.end_s, kind: x.kind, status: x.status}));
  }
  function matchingEpisode(a, b) {
    return !!a && !!b && ['id', 'start_s', 'end_s', 'kind', 'status', 'source', 'note'].every(k => (a[k] ?? '') === (b[k] ?? ''));
  }
  function append(document, item) {
    if (!document || !Array.isArray(document.episodes) || !document.bookmarks || typeof document.bookmarks !== 'object')
      throw Error('片段文档不完整，未保存');
    if (document.episodes.some(x => x.id === item.id)) throw Error('草稿标识已存在，请先重新读取核对');
    if (item.status === 'confirmed' && overlaps(item, document).some(x => x.status === 'confirmed'))
      throw Error('已确认 AF / AFL 片段不能重叠；请先核对现有片段');
    const result = clone(document); result.episodes.push(clone(item)); return result;
  }
  function overlayGeometry(draft, surface) {
    if (!draft || !currentSurface(draft.scope, surface)) return null;
    const {start_s, duration_s} = surface.wave, windowStart = start_s * 200,
      windowEnd = (start_s + duration_s) * 200, plot = surface.plot;
    const point = sample => integer(sample) ? sample : null;
    const start = point(draft.start_sample), end = point(draft.end_sample_exclusive);
    const x = sample => plot.left + (sample - windowStart) / (duration_s * 200) * plot.width;
    const inView = sample => sample !== null && sample >= windowStart && sample <= windowEnd;
    const shade = start !== null && end !== null && end > start && start < windowEnd && end > windowStart ?
      {x: x(Math.max(start, windowStart)), width: x(Math.min(end, windowEnd)) - x(Math.max(start, windowStart))} : null;
    return {start_x: inView(start) ? x(start) : null, end_x: inView(end) ? x(end) : null,
      start_offscreen: start !== null && !inView(start), end_offscreen: end !== null && !inView(end), shade,
      top: plot.top, height: plot.height};
  }
  function uuid() {
    if (!root.crypto?.randomUUID) throw Error('当前环境缺少安全草稿标识功能');
    return root.crypto.randomUUID();
  }
  function createSession(options) {
    if (typeof options.getScope !== 'function' || typeof options.api !== 'function') throw Error('缺少病例读取接口');
    const drafts = new Map(); let disposed = false, operation = null;
    const notify = () => { if (!disposed) options.onChange?.(); };
    const live = () => { if (disposed) return null; try { return scope(options.getScope()); } catch (_) { return null; } };
    const active = () => drafts.get(live()?.case_id) || null;
    function sync() {
      const s = live();
      for (const draft of drafts.values()) if (!same(draft.scope, s)) {
        draft.stale = true;
        if (operation?.draft === draft && !operation.sent && !same(operation.owner, s,
          operation.kind === 'reconcile' ? [...sourceKeys, 'caseToken', 'workspace_epoch'] : scopeKeys)) operation.controller.abort();
      }
      notify(); return snapshot();
    }
    function writable(draft, allowUncertain = false) {
      if (disposed || !draft || !same(draft.scope, live()) || draft.stale)
        throw Error('病例或修订已变化；旧草稿保留，但不能保存，请重新核对');
      if (operation) throw Error('正在读取或保存，请等待完成');
      if (draft.uncertain && !allowUncertain) throw Error('上次保存结果不确定，请先重新读取核对，不能重复保存');
    }
    function begin(sample = null) {
      const s = live(); if (!s) throw Error('当前病例依据尚未就绪');
      let draft = drafts.get(s.case_id);
      if (draft) writable(draft);
      else {
        draft = {id: (options.uuid || uuid)(), scope: s, start_sample: null, end_sample_exclusive: null,
          status: 'pending', note: '', base: null, stale: false, uncertain: false, submitted: null, error: '', message: ''};
        drafts.set(s.case_id, draft);
      }
      if (sample !== null) {
        if (!integer(sample) || sample >= s.sample_count) throw Error('起点必须是记录内的原始样本');
        draft.start_sample = sample;
      }
      draft.error = ''; notify(); return snapshot();
    }
    function update(fields) {
      const draft = active(); writable(draft);
      for (const key of ['start_sample', 'end_sample_exclusive']) if (key in fields) {
        const value = fields[key];
        if (value !== null && (!integer(value) || value > draft.scope.sample_count || (key === 'start_sample' && value === draft.scope.sample_count)))
          throw Error('片段边界超出原始样本范围');
      }
      if ('status' in fields) {
        if (!['pending', 'confirmed'].includes(fields.status)) throw Error('复核状态错误');
      }
      for (const key of ['start_sample', 'end_sample_exclusive', 'status']) if (key in fields) draft[key] = fields[key];
      if ('note' in fields) draft.note = String(fields.note).slice(0, 1000);
      draft.error = ''; draft.message = ''; notify(); return snapshot();
    }
    function cancel() {
      const draft = active();
      if (!draft) return false;
      if (operation?.draft === draft || draft.uncertain) throw Error('保存结果尚未核实，草稿标识保留；请先重新读取核对');
      drafts.delete(draft.scope.case_id); notify(); return true;
    }
    function url(draft, reconciliation = false) {
      const fields = {...Object.fromEntries(identityKeys.map(k => [k, draft.scope[k]]))};
      if (reconciliation) delete fields.analysis_revision;
      return '/api/cases/' + encodeURIComponent(draft.scope.case_id) + '/rhythm-review?' + new URLSearchParams(fields);
    }
    function response(value, draft, strict) {
      const s = identity(value);
      if (!same(draft.scope, s, sourceKeys) || (strict && s.analysis_revision !== draft.scope.analysis_revision) ||
          !integer(value.revision) || !Array.isArray(value.document?.episodes) ||
          !value.document.bookmarks || typeof value.document.bookmarks !== 'object')
        throw Error('片段响应与草稿依据不同，未使用旧响应');
      return value;
    }
    function stillOwner(draft) {
      const now = live();
      return !!now && same(draft.scope, now, [...sourceKeys, 'caseToken', 'workspace_epoch']);
    }
    async function accepted(draft, value, item, reconciled, owner = draft.scope) {
      draft.uncertain = false;
      drafts.delete(draft.scope.case_id);
      notify();
      if (!stillOwner({scope: owner}) || disposed) return {saved: true, current: false, reconciled};
      try {
        await options.onSaved?.({scope: clone(owner), draft_scope: clone(draft.scope), response: value, episode: clone(item), reconciled});
        return {saved: true, current: true, reconciled};
      } catch (_) {
        // A successful commit must never turn into a retryable save failure.
        options.onNotice?.('片段已保存，但新依据读取失败；请刷新核对，不要重复保存');
        return {saved: true, current: true, reconciled, refresh_failed: true};
      }
    }
    async function run(kind, task) {
      const draft = active();
      if (!draft || disposed || operation) throw Error('请先选择片段，或等待当前请求结束');
      if (kind !== 'reconcile') writable(draft);
      else if (!same(draft.scope, live(), [...sourceKeys, 'workspace_epoch']))
        throw Error('当前病例、源依据或心搏修订不同，不能核对旧草稿');
      const op = {draft, kind, owner: live(), controller: new AbortController(), sent: false}; operation = op;
      draft.error = ''; draft.message = ''; notify();
      try { return await task(draft, op); }
      catch (error) {
        if (op.sent) draft.uncertain = true;
        if (error.name !== 'AbortError') {
          draft.error = op.sent ? '保存结果未核实。草稿标识已保留，请重新读取核对；不要重复保存。' : error.message;
          if (!same(draft.scope, live())) draft.stale = true;
        }
        throw error;
      } finally {
        if (operation === op) operation = null;
        notify();
      }
    }
    const prepare = () => run('prepare', async (draft, op) => {
      const value = response(await options.api(url(draft), {method: 'GET', signal: op.controller.signal, readLane: 'rhythm-range-document'}), draft, true);
      if (!same(draft.scope, live()) || draft.stale) throw Error('读取期间病例或修订已变化，未采用旧片段文档');
      draft.base = clone(value); notify(); return snapshot();
    });
    const save = acknowledged => run('save', async (draft, op) => {
      if (acknowledged !== true) throw Error('请核对原始波形、片段范围与复核状态后勾选确认');
      if (options.canWrite && options.canWrite() !== true) throw Error('当前服务只读，未保存片段');
      const item = episode(draft);
      if (!draft.base) throw Error('请先读取现有片段，核对后保存');
      const value = response(await options.api(url(draft), {method: 'GET', signal: op.controller.signal, readLane: 'rhythm-range-save-check'}), draft, true);
      if (!same(draft.scope, live()) || draft.stale) throw Error('核对期间病例或修订已变化，未保存');
      const existing = value.document.episodes.find(x => x.id === item.id);
      if (existing) {
        if (!matchingEpisode(existing, item)) throw Error('同一草稿标识已有不同片段，请核对现有记录');
        return accepted(draft, value, item, true);
      }
      if (value.revision !== draft.base.revision || JSON.stringify(value.document) !== JSON.stringify(draft.base.document)) {
        draft.stale = true;
        throw Error('现有片段已变化，未自动追加；请重新核对草稿和片段文档');
      }
      const document = append(value.document, item);
      const payload = {...Object.fromEntries(identityKeys.map(k => [k, draft.scope[k]])),
        revision: value.revision, document, operation: 'save', confirmed: true};
      draft.submitted = clone(item); draft.uncertain = true; op.sent = true; notify();
      const result = response(await options.api(url(draft).split('?')[0], {method: 'PUT', body: JSON.stringify(payload)}), draft, false);
      if (result.revision !== value.revision + 1 || result.analysis_revision <= draft.scope.analysis_revision ||
          !matchingEpisode(result.document.episodes.find(x => x.id === item.id), item))
        throw Error('保存响应未能核实新片段和修订');
      return accepted(draft, result, item, false);
    });
    const reconcile = () => run('reconcile', async (draft, op) => {
      const item = draft.submitted || episode(draft);
      const value = response(await options.api(url(draft, true), {method: 'GET', signal: op.controller.signal, readLane: 'rhythm-range-reconcile'}), draft, false);
      if (!stillOwner({scope: op.owner})) throw Error('核对期间病例已变化，未使用旧响应');
      const existing = value.document.episodes.find(x => x.id === item.id);
      if (existing && matchingEpisode(existing, item)) return accepted(draft, value, item, true, op.owner);
      draft.message = existing ? '同一标识已有不同范围或状态；请核对现有片段，未再次保存。' :
        '最新文档未找到该草稿标识；保存结果仍未证实，保留草稿，未自动追加。';
      notify(); return {saved: false, unresolved: true, mismatch: !!existing};
    });
    function snapshot() {
      const draft = active();
      let item = null, error = null;
      if (draft) try { item = episode(draft); } catch (e) { error = e.message; }
      return {draft: draft ? clone(draft) : null, scope: live(), busy: !!operation,
        pending_count: drafts.size, current: !!draft && same(draft.scope, live()) && !draft.stale,
        range_error: error, overlaps: item && draft.base ? overlaps(item, draft.base.document) : []};
    }
    return {begin, update, cancel, prepare, save, reconcile, sync, snapshot,
      pending: () => drafts.size > 0, isSaving: () => !!operation?.sent,
      dispose() { disposed = true; if (operation && !operation.sent) operation.controller.abort(); }};
  }

  function mount(options) {
    if (!root.document) throw Error('波形分段编辑需要浏览器环境');
    const doc = root.document, surfaces = new Map(), fieldDrafts = new Map(); let menuContext = null, disposed = false;
    const dock = doc.createElement('section'); dock.className = 'rre-dock'; dock.hidden = true;
    dock.setAttribute('aria-label', '房颤片段草稿');
    dock.innerHTML = `<header><strong>房颤分段 · 手工标注</strong><output data-rre="state" aria-live="polite"></output></header>
      <form><div class="rre-fields"><label>起点（秒，含）<input name="start" type="number" min="0" step="0.005" required></label>
      <label>终点（秒，不含）<input name="end" type="number" min="0" step="0.005" required></label>
      <label>复核状态<select name="status"><option value="pending">待复核</option><option value="confirmed">医生确认</option></select></label>
      <label class="rre-note">备注<textarea name="note" rows="1" maxlength="1000"></textarea></label></div>
      <output data-rre="range"></output><p data-rre="boundary" class="rre-boundary"></p>
      <p data-rre="conflicts" class="rre-warning"></p><p data-rre="error" class="rre-error" role="alert"></p>
      <label class="rre-ack"><input name="ack" type="checkbox">我已核对波形、范围和所选复核状态</label>
      <footer><button type="button" data-rre="read">重新读取片段</button><button type="button" data-rre="reconcile">重新读取核对保存结果</button>
      <button type="button" data-rre="cancel">取消本地草稿</button><button type="submit" data-rre="save">保存待复核片段</button></footer></form>`;
    (options.host || doc.body).append(dock);
    const menu = doc.createElement('div'); menu.className = 'rre-menu'; menu.hidden = true; menu.setAttribute('role', 'menu');
    menu.innerHTML = `<strong>连续波形 · 房颤分段</strong><output data-rre="point"></output>
      <button type="button" data-rre="start" role="menuitem">设置房颤起点（含）</button>
      <button type="button" data-rre="end" role="menuitem">设置房颤终点（不含）</button>
      <button type="button" data-rre="manual" role="menuitem">输入片段边界…</button>
      <button type="button" data-rre="review" role="menuitem">核对并保存片段…</button>
      <button type="button" data-rre="beat" role="menuitem">心搏 / QRS 编辑…</button>
      <button type="button" data-rre="close" role="menuitem">关闭菜单（保留起止点）</button>`;
    doc.body.append(menu);
    const el = name => dock.querySelector(`[data-rre="${name}"]`), form = dock.querySelector('form');
    const session = createSession({...options, onChange: render});
    const safe = fn => Promise.resolve().then(fn).catch(error => {
      if (!disposed && error.name !== 'AbortError') {
        const message = session.snapshot().draft?.error || error.message;
        el('error').textContent = message; options.onError?.(new Error(message, {cause: error}));
      }
    });
    function fieldsFor(draft) {
      if (!fieldDrafts.has(draft.id)) fieldDrafts.set(draft.id, {
        start: draft.start_sample === null ? '' : (draft.start_sample / 200).toFixed(3),
        end: draft.end_sample_exclusive === null ? '' : (draft.end_sample_exclusive / 200).toFixed(3),
        status: draft.status, note: draft.note, error: ''});
      return fieldDrafts.get(draft.id);
    }
    function visibleFields(s) {
      return {start_sample: secondsSample(form.elements.start.value, s),
        end_sample_exclusive: secondsSample(form.elements.end.value, s),
        status: form.elements.status.value, note: form.elements.note.value};
    }
    function closeMenu() { menu.hidden = true; menuContext = null; }
    function drawOverlay(canvas, surface, draft) {
      let entry = surfaces.get(canvas);
      if (!entry) {
        const svg = doc.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.classList.add('rre-wave-overlay');
        svg.setAttribute('aria-hidden', 'true');
        const parent = canvas.parentElement, changed = root.getComputedStyle(parent).position === 'static';
        if (changed) parent.style.position = 'relative';
        canvas.after(svg); entry = {svg, parent, changed}; surfaces.set(canvas, entry);
      }
      const geometry = draft && !draft.stale ? overlayGeometry(draft, surface) : null;
      const rect = canvas.getBoundingClientRect(), parentRect = entry.parent.getBoundingClientRect();
      entry.svg.hidden = !geometry || !canvas.getClientRects().length || !rect.width || !rect.height;
      if (entry.svg.hidden) return;
      entry.svg.style.left = `${rect.left - parentRect.left + entry.parent.scrollLeft - entry.parent.clientLeft}px`;
      entry.svg.style.top = `${rect.top - parentRect.top + entry.parent.scrollTop - entry.parent.clientTop}px`;
      entry.svg.style.width = `${rect.width}px`; entry.svg.style.height = `${rect.height}px`;
      entry.svg.setAttribute('viewBox', `0 0 ${rect.width} ${rect.height}`);
      const line = (x, color, text) => x === null ? '' : `<line x1="${x}" x2="${x}" y1="${geometry.top}" y2="${geometry.top + geometry.height}" stroke="${color}" stroke-width="2"/><text x="${Math.min(rect.width - 76, Math.max(3, x + 4))}" y="${geometry.top + 14}" fill="${color}">${text}</text>`;
      entry.svg.innerHTML = (geometry.shade ? `<rect x="${geometry.shade.x}" y="${geometry.top}" width="${geometry.shade.width}" height="${geometry.height}" fill="rgba(8,119,119,.11)"/>` : '') +
        line(geometry.start_x, '#087777', '起点 · 含') + line(geometry.end_x, '#b36116', '终点 · 不含');
    }
    function render() {
      if (disposed) return;
      const s = session.snapshot(), draft = s.draft;
      dock.hidden = !draft;
      if (draft) {
        const fields = fieldsFor(draft);
        const disabled = s.busy || !s.current || draft.uncertain;
        for (const name of ['start', 'end', 'status', 'note']) form.elements[name].disabled = disabled;
        for (const name of ['start', 'end', 'status', 'note']) form.elements[name].value = fields[name];
        form.elements.start.max = draft.scope.duration_s; form.elements.end.max = draft.scope.duration_s;
        el('state').textContent = s.busy ? '正在读取或保存' : draft.uncertain ? '保存结果待核实' : !s.current ? '旧依据草稿 · 保留' : '本地未保存';
        el('range').textContent = s.range_error || `样本 [${draft.start_sample}, ${draft.end_sample_exclusive}) · ${(draft.end_sample_exclusive - draft.start_sample) / 200} 秒 · 200 Hz`;
        const off = [...surfaces.keys()].map(c => overlayGeometry(draft, options.getSurface(c))).filter(Boolean);
        const beyond = off.some(x => x.start_offscreen || x.end_offscreen) ? '部分边界在当前窗口之外，未绘制虚构端点。' : '';
        el('boundary').textContent = `原始采样网格 0.005 秒；起点包含，终点不包含。${beyond} ${draft.status === 'confirmed' ? '医生确认是诊断声明，保存后计入确认负荷。' : '待复核不计入确认负荷；按现有规则，待复核与确认段均排除窦性专用 NN 计算。'}`;
        el('conflicts').textContent = s.overlaps.length ? `与 ${s.overlaps.length} 条现有片段重叠：` + s.overlaps.map(x => `${x.kind} ${x.start_s.toFixed(3)}–${x.end_s.toFixed(3)} 秒（${statusName(x.status)}）`).join('；') + '。保留原段，不合并、不裁切。' : '';
        el('error').textContent = draft.error || draft.message || fields.error || (!s.current ? '病例或修订已变化，不能保存旧草稿。可取消本地草稿后重新选择。' : '');
        const blocked = draft.status === 'confirmed' && s.overlaps.some(x => x.status === 'confirmed');
        let invalidFields = false; try { visibleFields(draft.scope); } catch (_) { invalidFields = true; }
        el('save').disabled = disabled || !draft.base || !!s.range_error || invalidFields || blocked || !form.elements.ack.checked || (options.canWrite && !options.canWrite());
        el('save').textContent = draft.status === 'confirmed' ? '保存医生确认片段' : '保存待复核片段';
        el('read').disabled = disabled; el('reconcile').hidden = !draft.uncertain;
        el('reconcile').disabled = s.busy || !same(draft.scope, s.scope, [...sourceKeys, 'workspace_epoch']);
        el('cancel').disabled = s.busy || draft.uncertain;
      } else form.elements.ack.checked = false;
      for (const canvas of surfaces.keys()) drawOverlay(canvas, options.getSurface(canvas), draft);
    }
    async function prepareIfNeeded() { if (!session.snapshot().draft?.base) await session.prepare(); }
    function reveal() { render(); dock.scrollIntoView({block: 'nearest', behavior: 'smooth'}); }
    form.addEventListener('input', event => {
      form.elements.ack.checked = event.target.name === 'ack' ? event.target.checked : false;
      if (event.target.name === 'ack') return render();
      const draft = session.snapshot().draft;
      if (!draft) return;
      const fields = fieldsFor(draft); fields[event.target.name] = event.target.value;
      try {
        const update = {};
        if (event.target.name === 'start' || event.target.name === 'end') update[event.target.name === 'start' ? 'start_sample' : 'end_sample_exclusive'] = event.target.value === '' ? null : secondsSample(event.target.value, draft.scope);
        else update[event.target.name] = event.target.value;
        fields.error = ''; session.update(update);
      } catch (error) { fields.error = error.message; render(); }
    });
    form.addEventListener('submit', event => {
      event.preventDefault();
      safe(() => {
        const s = session.snapshot().draft?.scope;
        if (!s) throw Error('请先选择片段');
        // Read the visible fields again: an invalid partial number must never
        // silently save the previously valid range retained in the model.
        session.update(visibleFields(s));
        return session.save(form.elements.ack.checked);
      });
    });
    el('read').onclick = () => safe(() => session.prepare());
    el('reconcile').onclick = () => safe(() => session.reconcile());
    el('cancel').onclick = () => safe(() => { session.cancel(); closeMenu(); });
    menu.addEventListener('click', event => {
      const action = event.target.closest('button')?.dataset.rre, context = menuContext;
      if (!action || !context) return;
      if (action === 'close') return closeMenu();
      safe(async () => {
        const now = scope(options.getScope()), surface = options.getSurface(context.canvas);
        if (!same(now, context.scope) || !currentSurface(now, surface)) throw Error('菜单打开后病例或波形依据已变化，请重新选择');
        closeMenu();
        if (action === 'beat') return options.onBeatEditor?.(context.event, context.canvas);
        if (action === 'start') {
          session.begin(context.sample); fieldsFor(session.snapshot().draft).start = (context.sample / 200).toFixed(3);
          form.elements.ack.checked = false;
        }
        if (action === 'end') {
          session.update({end_sample_exclusive: context.sample}); fieldsFor(session.snapshot().draft).end = (context.sample / 200).toFixed(3);
          form.elements.ack.checked = false;
        }
        if (action === 'manual' && !session.snapshot().draft) session.begin();
        reveal();
        if (action !== 'review') await prepareIfNeeded();
        if (action === 'manual') form.elements.start.focus();
      });
    });
    menu.addEventListener('keydown', event => {
      if (!['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault(); event.stopPropagation();
      if (['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      const buttons = [...menu.querySelectorAll('button')].filter(b => !b.disabled), current = buttons.indexOf(doc.activeElement);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 :
        (current + (event.key === 'ArrowUp' ? -1 : 1) + buttons.length) % buttons.length;
      buttons[next]?.focus({preventScroll: true});
    });
    function openContext(event, config) {
      if (disposed || !config?.canvas) return false;
      event?.preventDefault?.();
      try {
        const s = scope(options.getScope()), surface = config.surface || options.getSurface(config.canvas);
        if (!currentSurface(s, surface)) throw Error('当前波形依据尚未核实，不能设置房颤边界或编辑旧心搏');
        let sample = null;
        if (config.keyboard) {
          if (integer(surface.cursor_sample) && surface.cursor_sample <= s.sample_count) sample = surface.cursor_sample;
        } else sample = pointerSample(s, surface, event.clientX - config.canvas.getBoundingClientRect().left);
        menuContext = {event, canvas: config.canvas, scope: s, sample};
        drawOverlay(config.canvas, surface, session.snapshot().draft);
        menu.querySelector('[data-rre="point"]').textContent = sample === null ? '未指定键盘边界位置，可输入精确秒数' : `原始样本 ${sample} · ${(sample / 200).toFixed(3)} 秒`;
        menu.querySelector('[data-rre="start"]').disabled = sample === null || sample >= s.sample_count || session.snapshot().busy;
        menu.querySelector('[data-rre="end"]').disabled = sample === null || !session.snapshot().draft || session.snapshot().busy;
        menu.querySelector('[data-rre="review"]').disabled = !session.snapshot().draft;
        menu.hidden = false;
        const rect = config.canvas.getBoundingClientRect(), x = config.keyboard ? rect.left + surface.plot.left : event.clientX,
          y = config.keyboard ? rect.top + surface.plot.top : event.clientY;
        menu.style.left = `${Math.max(8, Math.min(x, root.innerWidth - menu.offsetWidth - 8))}px`;
        menu.style.top = `${Math.max(8, Math.min(y, root.innerHeight - menu.offsetHeight - 8))}px`;
        [...menu.querySelectorAll('button')].find(b => !b.disabled)?.focus({preventScroll: true});
      } catch (error) { closeMenu(); options.onError?.(error); options.onNotice?.(error.message); }
      return true;
    }
    const outside = event => { if (!menu.hidden && !menu.contains(event.target)) closeMenu(); };
    const keydown = event => {
      if (event.key !== 'Escape') return;
      // The explicit QRS action hands keyboard ownership to the original menu.
      // Its listener runs later, so defaultPrevented alone cannot establish this
      // priority at document capture time. Preserve the AF draft while it closes.
      const beatMenu = doc.querySelector('#beatRelabelMenu');
      let beatPopover = false;
      try { beatPopover = !!beatMenu?.matches(':popover-open'); } catch (_) {}
      if (doc.querySelector('dialog[open]') || beatMenu && !beatMenu.hidden && (beatPopover || beatMenu.getClientRects().length)) return;
      if (event.defaultPrevented || (!dock.getClientRects().length && menu.hidden)) return;
      event.preventDefault(); event.stopImmediatePropagation(); closeMenu(); safe(() => session.cancel());
    };
    const redraw = () => { closeMenu(); render(); };
    doc.addEventListener('pointerdown', outside); doc.addEventListener('keydown', keydown, true);
    root.addEventListener('resize', redraw);
    return {openContext, sync() { closeMenu(); return session.sync(); }, snapshot: session.snapshot,
      pending: session.pending, isSaving: session.isSaving, closeMenu,
      cancelDraft: session.cancel, prepare: session.prepare, save: session.save, reconcile: session.reconcile,
      dispose() {
        disposed = true; session.dispose(); doc.removeEventListener('pointerdown', outside); doc.removeEventListener('keydown', keydown, true);
        root.removeEventListener('resize', redraw); menu.remove(); dock.remove();
        for (const {svg, parent, changed} of surfaces.values()) { svg.remove(); if (changed && parent.style.position === 'relative') parent.style.position = ''; }
        surfaces.clear(); fieldDrafts.clear();
      }};
  }
  const api = {mount, createSession, scope, identity, same, currentSurface, pointerSample, secondsSample, range, episode, overlaps, append, matchingEpisode, overlayGeometry};
  root.ECGRhythmRangeEditor = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
