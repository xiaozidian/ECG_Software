"use strict";
/* Local, versioned physician-selected phrases. No patient inference or diagnosis rules. */
globalThis.ECGTerminologyTree = (() => {
  const labels = {draft: '待核准', approved: '导入声明已核准', rejected: '导入声明未通过'};
  const copy = value => JSON.parse(JSON.stringify(value));
  const keyOf = value => JSON.stringify([value.namespace, value.version, value.sha256]);
  const catalogCacheLimit = 12;
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }
  function button(text, action) {
    const node = element('button', '', text);
    node.type = 'button';
    if (action) node.addEventListener('click', action);
    return node;
  }
  function scopeText(scope) {
    const names = {adult: '成人', pediatric: '儿童', resting_12lead: '静息12导联', holter: '动态心电'};
    return [...(scope?.population || []), ...(scope?.recording || [])].map(x => names[x] || x).join(' / ');
  }
  async function defaultApi(path, init) {
    const response = await fetch(path, init);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || data.message || '术语目录请求失败');
    return data;
  }
  function insertText(editor, text) {
    if (!editor || editor.readOnly || editor.disabled || typeof editor.value !== 'string' || !text) return null;
    const before = editor.value;
    const start = typeof editor.selectionStart === 'number' ? editor.selectionStart : before.length;
    const end = typeof editor.selectionEnd === 'number' ? editor.selectionEnd : start;
    if (editor.maxLength >= 0 && before.length + text.length > editor.maxLength) return null;
    // A physician's selected characters are preserved. Insert after the selection.
    if (typeof editor.setRangeText === 'function') editor.setRangeText(text, end, end, 'end');
    else editor.value = before.slice(0, end) + text + before.slice(end);
    return {before, after: editor.value, start, end};
  }
  function undoText(editor, insertion) {
    if (!insertion || !editor || editor.readOnly || editor.disabled || editor.value !== insertion.after) return false;
    editor.value = insertion.before;
    editor.setSelectionRange?.(insertion.start, insertion.end);
    return true;
  }
  function mount(host, options = {}) {
    if (!host) throw new Error('术语树需要可挂接的容器');
    host._ecgTerminologyTree?.destroy();
    let settings = {...options}, disposed = false, contextGeneration = 0, catalogGeneration = 0,
      listGeneration = 0, importGeneration = 0, editGeneration = 0, ownInput = false,
      catalog = null, selectedId = null, catalogRevision = 0, catalogs = [], stagedImport = null;
    let usages = copy(settings.usages || []), insertionHistory = [], boundEditor = null;
    const cache = new Map(), expansion = new Map();
    const api = (path, init) => (settings.api || defaultApi)(path, init);
    const editor = () => typeof settings.editor === 'function' ? settings.editor() : settings.editor;
    const contextKey = () => JSON.stringify([String(settings.caseId ?? ''), String(settings.reportContext ?? 'draft'), contextGeneration]);
    const current = () => !disposed && host.isConnected !== false && (!settings.isCurrent || settings.isCurrent());
    const shell = element('section', 'ecg-terminology-tree');
    shell.setAttribute('aria-label', '版本化术语树');
    const title = element('h3', '', '版本化术语树');
    const notice = element('p', 'tt-notice', '示例 / 待核准；医生需核对；非完整医院库。分组用于查找，不是医学本体。');
    const declaration = element('p', 'tt-declaration', '来源、许可、适用范围、完整性和核准状态按文件声明展示，软件未独立验证。');
    const tools = element('div', 'tt-tools');
    const selectLabel = element('label', '', '目录版本');
    const select = element('select'); select.setAttribute('data-tt-catalog', '');
    select.setAttribute('aria-label', '选择术语目录及版本'); selectLabel.append(select);
    const refresh = button('刷新目录', () => refreshCatalogs()); refresh.setAttribute('data-tt-refresh', '');
    tools.append(selectLabel, refresh);
    const info = element('p', 'tt-catalog-info'); info.setAttribute('data-tt-catalog-info', '');
    const searchLabel = element('label', 'tt-search', '搜索术语 / 同义词');
    const search = element('input'); search.type = 'search'; search.maxLength = 160;
    search.placeholder = '输入名称、正文或同义词'; search.setAttribute('data-tt-search', '');
    searchLabel.append(search);
    const controls = element('div', 'tt-expand-actions');
    const expand = button('展开全部', () => setExpanded(true)), collapse = button('折叠全部', () => setExpanded(false));
    expand.setAttribute('data-tt-expand-all', ''); collapse.setAttribute('data-tt-collapse-all', '');
    controls.append(expand, collapse);
    const status = element('p', 'tt-status', '正在读取本地目录…'); status.setAttribute('role', 'status'); status.setAttribute('data-tt-status', '');
    const columns = element('div', 'tt-columns');
    const tree = element('div', 'tt-tree'); tree.setAttribute('role', 'tree'); tree.setAttribute('aria-label', '术语分组及词条'); tree.setAttribute('data-tt-tree', '');
    const preview = element('section', 'tt-preview'); preview.setAttribute('aria-label', '术语原文预览'); preview.setAttribute('data-tt-preview', '');
    const actions = element('div', 'tt-insert-actions');
    const insert = button('明确插入原文', insertSelected); insert.disabled = true; insert.setAttribute('data-tt-insert', '');
    const undo = button('撤销上次术语插入', undoLast); undo.disabled = true; undo.setAttribute('data-tt-undo', '');
    actions.append(insert, undo);
    const usageInfo = element('p', 'tt-usage-info'); usageInfo.setAttribute('data-tt-usages', '');
    columns.append(tree, preview);
    const importPanel = element('details', 'tt-import');
    importPanel.append(element('summary', '', '导入本地版本化 JSON 目录'));
    importPanel.append(element('p', '', '选择文件后先预览，明确确认后仅发布到本机。请确认你拥有使用和分发该内容的权利。已有版本不可覆盖。'));
    const fileLabel = element('label', '', '本地 JSON 文件');
    const file = element('input'); file.type = 'file'; file.accept = '.json,application/json'; file.setAttribute('data-tt-import-file', '');
    fileLabel.append(file); importPanel.append(fileLabel);
    const importPreview = element('div', 'tt-import-preview'); importPreview.setAttribute('data-tt-import-preview', '');
    const confirmLabel = element('label', 'tt-import-consent');
    const consent = element('input'); consent.type = 'checkbox'; consent.setAttribute('data-tt-import-consent', '');
    confirmLabel.append(consent, document.createTextNode('我已核对导入内容及其来源和许可声明，确认本地发布此版本。'));
    const confirm = button('明确确认并本地发布', confirmImport); confirm.disabled = true; confirm.setAttribute('data-tt-import-confirm', '');
    importPanel.append(importPreview, confirmLabel, confirm);
    shell.append(title, notice, declaration, tools, info, searchLabel, controls, status, columns, actions, usageInfo, importPanel);
    host.replaceChildren(shell);

    function say(message) { if (current()) status.textContent = message; }
    function appendField(parent, name, value) {
      const line = element('p', 'tt-meta'); line.append(element('strong', '', name + '：'), document.createTextNode(String(value ?? ''))); parent.append(line);
    }
    function metadata(parent, value, identity) {
      if (identity) {
        appendField(parent, '命名空间 / 版本', value.namespace + ' / ' + value.version);
        appendField(parent, 'SHA-256', value.sha256);
      }
      appendField(parent, '核准状态（声明）', labels[value.approval] || value.approval);
      appendField(parent, '来源（声明）', (value.source?.name || '') + (value.source?.url ? ' · ' + value.source.url : ''));
      appendField(parent, '许可（声明）', (value.license?.name || '') + (value.license?.url ? ' · ' + value.license.url : ''));
      appendField(parent, '适用范围（声明）', scopeText(value.scope));
      if (value.review?.reviewer || value.review?.reviewed_at) appendField(parent, '审核记录（声明）', [value.review.reviewer, value.review.reviewed_at].filter(Boolean).join(' · '));
      const licenseDetails = element('details', 'tt-license'); licenseDetails.append(element('summary', '', '查看许可原文'), element('pre', '', value.license?.text || '')); parent.append(licenseDetails);
    }
    function canInsert(node) {
      const target = editor();
      return current() && !!catalog && node?.kind === 'term' && !node.deprecated && node.approval !== 'rejected' && catalog.approval !== 'rejected'
        && !!target && !target.readOnly && !target.disabled;
    }
    function updateUndo() {
      const last = insertionHistory.at(-1), target = editor();
      undo.disabled = !(current() && last && last.editor === target && last.context === contextKey()
        && last.editGeneration === editGeneration && target.value === last.after && !target.disabled && !target.readOnly);
      usageInfo.textContent = `此报告保存 ${usages.length} 条术语使用快照。正文后续编辑不按词库更新自动重写。`;
    }
    function bindEditor() {
      const target = editor();
      if (boundEditor === target) return;
      boundEditor?.removeEventListener('input', onEditorInput);
      boundEditor = target;
      boundEditor?.addEventListener('input', onEditorInput);
    }
    function onEditorInput() {
      if (!ownInput) { editGeneration++; insertionHistory = []; }
      updateUndo();
      const node = catalog?.nodes.find(n => n.stable_id === selectedId);
      insert.disabled = !canInsert(node);
    }
    function showPreview() {
      preview.replaceChildren();
      const node = catalog?.nodes.find(n => n.stable_id === selectedId);
      insert.disabled = !canInsert(node);
      if (!node) { preview.append(element('p', 'tt-empty', '选择词条查看原文；预览和展开不会修改报告。')); return; }
      preview.append(element('h4', '', node.label));
      if (node.kind === 'group') {
        preview.append(element('p', 'tt-notice', '此节点是查找分组，不能插入报告，也不表示医学本体关系。')); return;
      }
      const text = element('pre', 'tt-original', node.text); text.setAttribute('data-tt-original', ''); preview.append(text);
      appendField(preview, '稳定词条标识', node.stable_id);
      appendField(preview, '目录版本 / SHA-256', catalog.version + ' / ' + catalog.sha256);
      metadata(preview, node, false);
      if (node.aliases.length) appendField(preview, '同义检索词', node.aliases.join(' / '));
      if (node.deprecated) preview.append(element('p', 'tt-notice', '此词条已废弃，不能新增插入。' + (node.replacement_id ? '替代词条标识：' + node.replacement_id : '')));
      preview.append(element('p', 'tt-declaration', '医生需核对具体病例。只有点击“明确插入原文”才写入报告；不会自动补患者信息或确立诊断。'));
    }
    function expandedSet() {
      const key = contextKey() + keyOf(catalog);
      if (!expansion.has(key)) expansion.set(key, new Set(catalog.nodes.filter(n => n.kind === 'group' && n.parent_id === null).map(n => n.stable_id)));
      return expansion.get(key);
    }
    function setExpanded(value) {
      if (!catalog || !current()) return;
      const set = expandedSet(); set.clear();
      if (value) catalog.nodes.filter(n => n.kind === 'group').forEach(n => set.add(n.stable_id));
      renderTree();
    }
    function renderTree() {
      tree.replaceChildren();
      expand.disabled = collapse.disabled = !catalog;
      if (!catalog) return;
      const query = search.value.trim().toLocaleLowerCase();
      const lookup = new Map(catalog.nodes.map(n => [n.stable_id, n])), children = new Map(), visible = new Set(), hits = new Set();
      catalog.nodes.forEach(node => {
        if (!children.has(node.parent_id)) children.set(node.parent_id, []);
        children.get(node.parent_id).push(node);
        if (!query || [node.label, node.text, ...node.aliases].some(text => text.toLocaleLowerCase().includes(query))) {
          hits.add(node.stable_id);
          let cursor = node;
          for (let depth = 0; cursor && depth < 9; depth++) { visible.add(cursor.stable_id); cursor = lookup.get(cursor.parent_id); }
        }
      });
      // A matching group also displays its descendants for navigation.
      if (query) catalog.nodes.forEach(node => {
        let cursor = lookup.get(node.parent_id);
        for (let depth = 0; cursor && depth < 9; depth++) {
          if (hits.has(cursor.stable_id)) { visible.add(node.stable_id); break; }
          cursor = lookup.get(cursor.parent_id);
        }
      });
      const expanded = expandedSet();
      function branch(parent, depth) {
        const list = element('ul'); list.setAttribute('role', 'group');
        (children.get(parent) || []).filter(n => visible.has(n.stable_id)).forEach(node => {
          const row = element('li', 'tt-row'); row.setAttribute('role', 'none');
          const item = button((node.kind === 'group' ? '▸ ' : '') + node.label + (node.kind === 'term' ? ' · ' + labels[node.approval] : ''), () => {
            if (!current()) return;
            selectedId = node.stable_id;
            if (node.kind === 'group') { if (expanded.has(node.stable_id)) expanded.delete(node.stable_id); else expanded.add(node.stable_id); }
            renderTree(); showPreview();
            [...tree.querySelectorAll('[data-tt-node]')].find(n => n.dataset.ttNode === node.stable_id)?.focus({preventScroll: true});
          });
          item.setAttribute('role', 'treeitem'); item.setAttribute('aria-level', String(depth)); item.setAttribute('aria-selected', String(selectedId === node.stable_id));
          item.setAttribute('data-tt-node', node.stable_id); item.setAttribute('data-tt-kind', node.kind);
          if (node.kind === 'group') {
            const open = !!query || expanded.has(node.stable_id); item.setAttribute('aria-expanded', String(open));
            item.textContent = (open ? '▾ ' : '▸ ') + node.label;
            item.addEventListener('keydown', event => {
              if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
              event.preventDefault(); if (event.key === 'ArrowRight') expanded.add(node.stable_id); else expanded.delete(node.stable_id);
              renderTree(); [...tree.querySelectorAll('[data-tt-node]')].find(n => n.dataset.ttNode === node.stable_id)?.focus({preventScroll: true});
            });
            row.append(item); if (open) row.append(branch(node.stable_id, depth + 1));
          } else { if (node.deprecated) item.textContent += ' · 已废弃'; row.append(item); }
          list.append(row);
        });
        return list;
      }
      tree.append(branch(null, 1));
      if (!visible.size) tree.append(element('p', 'tt-empty', '没有匹配术语。请更换检索词。'));
      else if (query) tree.prepend(element('p', 'tt-search-count', `匹配 ${hits.size} 个节点（包含分组）；搜索只改变显示。`));
    }
    function acceptCatalog(value, ref) {
      if (!value || !Array.isArray(value.nodes) || value.nodes.length > 1200 || !/^[0-9a-f]{64}$/.test(value.sha256 || '')
          || value.namespace !== ref.namespace || value.version !== ref.version || (ref.sha256 && value.sha256 !== ref.sha256)) throw new Error('返回目录身份不匹配');
      catalog = copy(value); selectedId = null;
      info.textContent = `${catalog.title} · ${catalog.namespace} / ${catalog.version} · ${labels[catalog.approval]} · ${catalog.completeness === 'example' ? '示例 / 非完整医院库' : '完整性按导入声明：' + catalog.completeness} · SHA-256 ${catalog.sha256}`;
      renderTree(); showPreview(); updateUndo();
      say('已加载该版本；请选择词条预览原文。来源和核准状态未独立验证。');
    }
    async function loadCatalog(ref) {
      if (!ref || !current()) return false;
      const request = ++catalogGeneration, context = contextKey(), cacheKey = context + keyOf(ref);
      catalog = null; selectedId = null; info.textContent = ''; renderTree(); showPreview(); say('正在读取选定术语版本…');
      const match = catalogs.findIndex(item => keyOf(item) === keyOf(ref));
      if (match >= 0) select.value = String(match);
      try {
        let value = cache.get(cacheKey);
        if (!value) {
          const params = new URLSearchParams({namespace: ref.namespace, version: ref.version});
          if (ref.sha256) params.set('hash', ref.sha256);
          const response = await api('/api/terminology/catalog?' + params);
          value = response.catalog || response;
          if (!current() || request !== catalogGeneration || context !== contextKey()) return false;
          cache.set(cacheKey, copy(value));
          if (cache.size > catalogCacheLimit) cache.delete(cache.keys().next().value);
        }
        if (!current() || request !== catalogGeneration || context !== contextKey()) return false;
        acceptCatalog(value, ref); return true;
      } catch (error) { if (current() && request === catalogGeneration && context === contextKey()) say('目录读取失败：' + error.message); return false; }
    }
    async function refreshCatalogs() {
      if (!current()) return false;
      const request = ++listGeneration, context = contextKey(), selectionAtStart = catalogGeneration;
      refresh.disabled = true;
      try {
        const response = await api('/api/terminology/catalogs');
        if (!current() || request !== listGeneration || context !== contextKey() || selectionAtStart !== catalogGeneration) return false;
        catalogs = copy(response.items || []); catalogRevision = response.catalog_revision;
        const selectedKey = catalog && keyOf(catalog);
        select.replaceChildren();
        catalogs.forEach((item, index) => { const option = element('option', '', `${item.title} · ${item.version} · ${labels[item.approval]}${item.builtin ? ' · 原创示例' : ''}`); option.value = String(index); select.append(option); });
        const active = selectedKey ? catalogs.findIndex(item => keyOf(item) === selectedKey) : -1;
        if (active >= 0) select.value = String(active);
        else if (catalogs.length && !catalog) await loadCatalog(catalogs[0]);
        else if (!catalogs.length) say('尚无可选目录。可导入你有权使用的版本化 JSON。');
        return true;
      } catch (error) { if (current() && request === listGeneration && context === contextKey()) say('目录列表读取失败：' + error.message); return false; }
      finally { if (current() && request === listGeneration && context === contextKey()) refresh.disabled = false; }
    }
    function insertSelected() {
      bindEditor();
      const node = catalog?.nodes.find(n => n.stable_id === selectedId);
      if (!canInsert(node)) return false;
      if (usages.length >= 500) { say('此报告的术语使用记录已达 500 条限制。'); return false; }
      const target = editor(), insertion = insertText(target, node.text);
      if (!insertion) { say('当前结论无法插入，请核对编辑状态和长度限制。'); return false; }
      const usage = {
        usage_id: 'term-' + (globalThis.crypto?.randomUUID?.() || Date.now().toString(36) + '-' + Math.random().toString(36).slice(2)),
        namespace: catalog.namespace, version: catalog.version, catalog_hash: catalog.sha256,
        stable_id: node.stable_id, label: node.label, inserted_text: node.text, approval: node.approval,
        source: copy(node.source), license: copy(node.license), scope: copy(node.scope), review: copy(node.review), inserted_at: new Date().toISOString()
      };
      usages.push(usage);
      insertionHistory.push({...insertion, usageId: usage.usage_id, editor: target, context: contextKey(), editGeneration});
      settings.onUsageDirty?.(copy(usages));
      settings.onInsert?.(copy(usage), {...insertion});
      ownInput = true; try { target.dispatchEvent(new Event('input', {bubbles: true})); } finally { ownInput = false; }
      target.focus?.({preventScroll: true}); updateUndo(); say('已按明确选择插入原文，并保留版本快照；医生仍需核对。'); return true;
    }
    function undoLast() {
      bindEditor(); updateUndo(); if (undo.disabled) return false;
      const last = insertionHistory.at(-1), target = editor();
      if (!undoText(target, last)) return false;
      insertionHistory.pop(); usages = usages.filter(item => item.usage_id !== last.usageId);
      settings.onUsageDirty?.(copy(usages));
      ownInput = true; try { target.dispatchEvent(new Event('input', {bubbles: true})); } finally { ownInput = false; }
      target.focus?.({preventScroll: true}); updateUndo(); say('已撤销上次术语插入。'); return true;
    }
    async function previewImport(value) {
      if (!current()) return false;
      const request = ++importGeneration, context = contextKey(); stagedImport = null; consent.checked = false; confirm.disabled = true;
      importPreview.replaceChildren(element('p', '', '正在校验并预览本地目录…'));
      try {
        const response = await api('/api/terminology/import', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({catalog: value, expected_catalog_revision: catalogRevision, confirm: false})});
        if (!current() || request !== importGeneration || context !== contextKey()) return false;
        if (!response.preview_only || !response.catalog || response.preview_hash !== response.catalog.sha256) throw new Error('导入预览身份不匹配');
        stagedImport = copy(response); catalogRevision = response.catalog_revision;
        importPreview.replaceChildren(element('h4', '', response.catalog.title)); metadata(importPreview, response.catalog, true);
        appendField(importPreview, '目录规模', `${response.catalog.nodes.length} 个节点；${response.catalog.nodes.filter(n => n.kind === 'term').length} 个词条`);
        appendField(importPreview, '完整性（声明）', response.catalog.completeness);
        const original = element('details', 'tt-import-content'); original.append(element('summary', '', '检查全部词条原文'));
        const rows = element('ul'); response.catalog.nodes.forEach(node => {
          const item = element('li'); item.append(element('strong', '', node.label + ' · ' + node.stable_id + ' · ' + (node.kind === 'group' ? '查找分组' : labels[node.approval])));
          if (node.kind === 'term') item.append(element('pre', '', node.text));
          appendField(item, '父分组 / 废弃 / 替代词条', (node.parent_id || '根节点') + ' / ' + (node.deprecated ? '是' : '否') + ' / ' + (node.replacement_id || '无'));
          const details = element('details'); details.append(element('summary', '', '核对该节点的来源、许可、适用范围和审核声明')); metadata(details, node, false); item.append(details); rows.append(item);
        }); original.append(rows); importPreview.append(original);
        (response.warnings || []).forEach(message => importPreview.append(element('p', 'tt-notice', message)));
        say('导入校验通过，目录尚未发布。核对完整内容与来源许可后，可明确确认本地发布。'); return true;
      } catch (error) { if (current() && request === importGeneration && context === contextKey()) { importPreview.replaceChildren(element('p', 'tt-notice', '导入失败：' + error.message)); say('导入未发布。'); } return false; }
    }
    async function confirmImport() {
      if (!current() || !stagedImport || !consent.checked || confirm.disabled) return false;
      const request = importGeneration, context = contextKey(), staged = copy(stagedImport); confirm.disabled = true;
      try {
        const response = await api('/api/terminology/import', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({catalog: staged.catalog, expected_catalog_revision: staged.catalog_revision, confirm: true, preview_hash: staged.preview_hash})});
        if (!current() || request !== importGeneration || context !== contextKey()) return false;
        if (response.preview_only !== false || response.preview_hash !== staged.preview_hash) throw new Error('发布回应与确认版本不匹配');
        stagedImport = null; consent.checked = false; catalogRevision = response.catalog_revision;
        importPreview.replaceChildren(element('p', '', '此版本已发布到本机。来源和审核状态仍为文件声明；请选择目录版本后使用。'));
        await refreshCatalogs(); say('此版本已本地发布；已保存报告的术语原文快照保持不变。'); return true;
      } catch (error) { if (current() && request === importGeneration && context === contextKey()) { stagedImport = null; consent.checked = false; importPreview.replaceChildren(element('p', 'tt-notice', '发布失败：' + error.message + '。请刷新目录并重新预览。')); } return false; }
    }
    file.addEventListener('change', async () => {
      const chosen = file.files?.[0], request = ++importGeneration, context = contextKey(); stagedImport = null; consent.checked = false; confirm.disabled = true;
      if (!chosen || !current()) return;
      if (chosen.size > 1048576) { importPreview.replaceChildren(element('p', 'tt-notice', '文件超过 1 MiB 大小限制。')); return; }
      try { const value = JSON.parse(await chosen.text()); if (current() && request === importGeneration && context === contextKey()) await previewImport(value); }
      catch (error) { if (current() && request === importGeneration && context === contextKey()) importPreview.replaceChildren(element('p', 'tt-notice', 'JSON 读取失败：' + error.message)); }
    });
    consent.addEventListener('change', () => { confirm.disabled = !(current() && stagedImport && consent.checked); });
    select.addEventListener('change', () => { const ref = catalogs[Number(select.value)]; if (ref) loadCatalog(ref); });
    search.addEventListener('input', () => { if (current()) renderTree(); });
    tree.addEventListener('keydown', event => {
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp' && event.key !== 'Home' && event.key !== 'End') return;
      const items = [...tree.querySelectorAll('[data-tt-node]')], index = items.indexOf(document.activeElement);
      if (index < 0) return;
      event.preventDefault(); const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : Math.max(0, Math.min(items.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)));
      items[next]?.focus({preventScroll: true});
    });
    const controller = {
      destroy() { if (disposed) return; disposed = true; contextGeneration++; catalogGeneration++; listGeneration++; importGeneration++; cache.clear(); expansion.clear(); insertionHistory = []; boundEditor?.removeEventListener('input', onEditorInput); if (host._ecgTerminologyTree === controller) delete host._ecgTerminologyTree; },
      getUsages: () => copy(usages), loadCatalog, refreshCatalogs, previewImport, confirmImport, insertSelected, undoLast,
      setContext(next) {
        if (disposed) return;
        settings = {...settings, ...next}; contextGeneration++; catalogGeneration++; listGeneration++; importGeneration++; editGeneration++;
        cache.clear(); expansion.clear(); insertionHistory = []; usages = copy(next.usages || []); catalog = null; selectedId = null; stagedImport = null;
        consent.checked = false; confirm.disabled = true; search.value = ''; importPreview.replaceChildren(); info.textContent = ''; bindEditor(); renderTree(); showPreview(); updateUndo();
        return refreshCatalogs();
      }
    };
    host._ecgTerminologyTree = controller; bindEditor(); showPreview(); updateUndo();
    controller.ready = refreshCatalogs();
    return controller;
  }
  return {mount, insertText, undoText, scopeText};
})();
if (typeof module !== 'undefined' && module.exports) module.exports = globalThis.ECGTerminologyTree;
