'use strict';

// Offline only: this harness uses synthetic intervals and a parsed fake DOM.
// It never starts a server, launches a browser, or opens a clinical recording.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const decode = value => String(value).replace(/&quot;/g, '"').replace(/&#39;|&#x27;/g, "'")
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/&nbsp;/g, ' ');
const escape = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const dataKey = name => name.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase());
const voidTags = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr']);

class TextNode {
  constructor(value) { this.value = decode(value); this.parentNode = null; }
  get textContent() { return this.value; }
  set textContent(value) { this.value = String(value); }
  get outerHTML() { return escape(this.value); }
}

class Element {
  constructor(tagName = 'div', attributes = {}) {
    this.tagName = tagName.toUpperCase();
    this.attributes = Object.create(null);
    this.dataset = Object.create(null);
    this.children = [];
    this.parentNode = null;
    this.listeners = new Map();
    this.style = {};
    this.scrollTop = 0;
    this.clientWidth = 720;
    this.clientHeight = 240;
    this.width = 720;
    this.height = 240;
    this.disabled = false;
    this.checked = false;
    this.value = '';
    this._connected = true;
    for (const [key, value] of Object.entries(attributes)) this.setAttribute(key, value);
    const element = this;
    this.classList = {
      contains: name => element.className.split(/\s+/).includes(name),
      add(...names) { element.className = [...new Set([...element.className.split(/\s+/).filter(Boolean), ...names])].join(' '); },
      remove(...names) { element.className = element.className.split(/\s+/).filter(name => name && !names.includes(name)).join(' '); },
      toggle(name, force) { const enabled = force === undefined ? !this.contains(name) : !!force; enabled ? this.add(name) : this.remove(name); return enabled; },
    };
  }
  get isConnected() { return this._connected && (!this.parentNode || this.parentNode.isConnected); }
  set isConnected(value) { this._connected = !!value; }
  get parentElement() { return this.parentNode instanceof Element ? this.parentNode : null; }
  get childNodes() { return this.children; }
  get className() { return this.getAttribute('class') || ''; }
  set className(value) { this.setAttribute('class', value); }
  get id() { return this.getAttribute('id') || ''; }
  set id(value) { this.setAttribute('id', value); }
  setAttribute(key, value) {
    const text = String(value);
    this.attributes[key] = text;
    if (key.startsWith('data-')) this.dataset[dataKey(key)] = text;
    if (key === 'value') this.value = text;
    if (key === 'checked') this.checked = true;
    if (key === 'disabled') this.disabled = true;
    if (key === 'width' || key === 'height') this[key] = Number(text);
  }
  getAttribute(key) { return Object.hasOwn(this.attributes, key) ? this.attributes[key] : null; }
  hasAttribute(key) { return Object.hasOwn(this.attributes, key); }
  removeAttribute(key) {
    delete this.attributes[key];
    if (key.startsWith('data-')) delete this.dataset[dataKey(key)];
    if (key === 'checked') this.checked = false;
    if (key === 'disabled') this.disabled = false;
  }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  append(...children) { for (const child of children) this.appendChild(typeof child === 'string' ? new TextNode(child) : child); }
  replaceChildren(...children) { for (const child of this.children) child.parentNode = null; this.children = []; this.append(...children); }
  remove() { if (!this.parentNode) return; this.parentNode.children = this.parentNode.children.filter(child => child !== this); this.parentNode = null; this._connected = false; }
  get textContent() { return this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this.replaceChildren(new TextNode(value == null ? '' : value)); }
  get innerHTML() { return this.children.map(child => child.outerHTML).join(''); }
  set innerHTML(html) {
    this.replaceChildren();
    const stack = [this];
    for (const token of String(html).match(/<!--[\s\S]*?-->|<[^>]*>|[^<]+/g) || []) {
      if (token.startsWith('<!--') || token.startsWith('<!')) continue;
      if (token.startsWith('</')) {
        const tag = token.match(/^<\/\s*([^\s>]+)/)?.[1]?.toUpperCase();
        for (let i = stack.length - 1; i > 0; i--) if (stack[i].tagName === tag) { stack.length = i; break; }
      } else if (token.startsWith('<')) {
        const match = token.match(/^<\s*([^\s/>]+)([\s\S]*?)\/?\s*>$/);
        if (!match) continue;
        const attrs = {};
        for (const attr of match[2].matchAll(/([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g))
          attrs[attr[1]] = decode(attr[2] ?? attr[3] ?? attr[4] ?? '');
        const element = new Element(match[1], attrs);
        stack.at(-1).appendChild(element);
        if (!voidTags.has(match[1].toLowerCase()) && !token.endsWith('/>')) stack.push(element);
      } else stack.at(-1).appendChild(new TextNode(token));
    }
    for (const select of this.querySelectorAll('select')) {
      const options = select.querySelectorAll('option');
      select.value = (options.find(option => option.hasAttribute('selected')) || options[0])?.getAttribute('value') || '';
    }
  }
  get outerHTML() {
    const attrs = Object.entries(this.attributes).map(([key, value]) => ` ${key}="${escape(value)}"`).join('');
    const tag = this.tagName.toLowerCase();
    return `<${tag}${attrs}>${voidTags.has(tag) ? '' : this.innerHTML + `</${tag}>`}`;
  }
  matches(selector) {
    return selector.split(',').some(candidate => {
      candidate = candidate.trim();
      const not = candidate.match(/:not\(([^)]+)\)/);
      if (not) { candidate = candidate.replace(not[0], ''); if (this.matches(not[1])) return false; }
      if (candidate.endsWith(':checked')) { candidate = candidate.slice(0, -8); if (!this.checked) return false; }
      const tag = candidate.match(/^[a-zA-Z][\w-]*/)?.[0];
      if (tag && this.tagName !== tag.toUpperCase()) return false;
      for (const match of candidate.matchAll(/#([\w-]+)/g)) if (this.id !== match[1]) return false;
      for (const match of candidate.matchAll(/\.([\w-]+)/g)) if (!this.classList.contains(match[1])) return false;
      for (const match of candidate.matchAll(/\[([^\s=\]]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\]]+)))?\]/g)) {
        if (!this.hasAttribute(match[1])) return false;
        const expected = match[2] ?? match[3] ?? match[4];
        if (expected !== undefined && this.getAttribute(match[1]) !== expected.trim()) return false;
      }
      return true;
    });
  }
  querySelectorAll(selector) {
    const descendants = [];
    const visit = node => { for (const child of node.children) if (child instanceof Element) { descendants.push(child); visit(child); } };
    visit(this);
    const selectors = selector.split(',').map(part => part.trim());
    return descendants.filter(element => selectors.some(candidate => {
      const parts = candidate.split(/\s+(?![^\[]*\])/);
      if (!element.matches(parts.at(-1))) return false;
      let parent = element.parentElement;
      for (let i = parts.length - 2; i >= 0; i--) { while (parent && !parent.matches(parts[i])) parent = parent.parentElement; if (!parent) return false; parent = parent.parentElement; }
      return true;
    }));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { for (let node = this; node; node = node.parentElement) if (node.matches(selector)) return node; return null; }
  contains(other) { for (let node = other; node; node = node.parentNode) if (node === this) return true; return false; }
  addEventListener(type, listener) { if (!this.listeners.has(type)) this.listeners.set(type, new Set()); this.listeners.get(type).add(listener); }
  removeEventListener(type, listener) { this.listeners.get(type)?.delete(listener); }
  dispatchEvent(event) {
    event.target ||= this;
    event.preventDefault ||= function () { this.defaultPrevented = true; };
    event.stopPropagation ||= function () { this.cancelBubble = true; };
    for (let node = this; node; node = event.bubbles === false || event.cancelBubble ? null : node.parentElement) {
      event.currentTarget = node;
      for (const listener of node.listeners.get(event.type) || []) listener.call(node, event);
      if (typeof node['on' + event.type] === 'function') node['on' + event.type](event);
    }
    return !event.defaultPrevented;
  }
  click() { if (!this.disabled) this.dispatchEvent({type: 'click', bubbles: true}); }
  focus() { this.focused = true; }
  getBoundingClientRect() { return {left: 0, top: 0, width: this.clientWidth, height: this.clientHeight, right: this.clientWidth, bottom: this.clientHeight}; }
  getContext() {
    if (!this.context) this.context = new Proxy({canvas: this, measureText: text => ({width: String(text).length * 7})}, {
      get(target, key) { return key in target ? target[key] : () => {}; }, set(target, key, value) { target[key] = value; return true; },
    });
    return this.context;
  }
}

const root = path.resolve(__dirname, '..');
const sourcePath = process.env.RR_REVIEW_SOURCE || path.join(root, 'static/js/rr-review-workbench.js');
const CASE_ID = 'synthetic / RR';
const basis = Object.freeze({analysis_basis: 'synthetic-rr-basis', analysis_revision: 7, beat_revision: 3});
const plain = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setImmediate(resolve));
async function settle() { await tick(); await tick(); }
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; }

function item(index, overrides = {}) {
  const previous = index * 200, sample = previous + 160;
  const target = {...basis, case_id: CASE_ID, caseId: CASE_ID, sample_index: sample, beat_id: 's:' + sample,
    interval_start_sample: previous, interval_end_sample: sample};
  return {id: `rr:${previous}:${sample}`, ordinal: index + 1, interval_index: index, start_sample: previous, end_sample: sample,
    left: {id: 's:' + previous, sample_index: previous, classification_source: 'synthetic source annotation'},
    right: {id: 's:' + sample, sample_index: sample, classification_source: 'synthetic source annotation'},
    left_sample_index: previous, right_sample_index: sample,
    left_beat_id: 's:' + previous, right_beat_id: 's:' + sample, time_s: sample / 200,
    left_type: 'N', right_type: 'N', pair_type: '["N","N"]', rr_ms: 800, ratio_pct: 100, hr_bpm: 75,
    quality: {valid: true, reason: null}, type_known: true, nn_eligible_current_rules: true,
    valid_rr: true, nn_eligible: true, target, ...overrides};
}
function response(request, {total = 205, items, duration_s = 1000, ...overrides} = {}) {
  const params = Object.fromEntries(request.url.searchParams);
  // Match query_rr(): omitted UI time bounds echo as the effective record range.
  const query = {mode: params.mode || 'rr', population: params.population || 'all', quality: params.quality || 'all',
    pair_type: params.pair_type || 'all', start_s: params.start_s === undefined ? 0 : Number(params.start_s),
    end_s: params.end_s === undefined ? duration_s : Number(params.end_s),
    range_min: params.range_min === undefined ? null : Number(params.range_min),
    range_max: params.range_max === undefined ? null : Number(params.range_max),
    offset: Number(params.offset || 0), limit: Number(params.limit || 20)};
  const {offset, limit} = query;
  const count = Math.max(0, Math.min(limit, total - offset));
  return {...basis, case_id: CASE_ID, sample_rate_hz: 200, duration_s,
    query, total, offset, limit, has_previous: offset > 0, has_next: offset + count < total,
    items: items || Array.from({length: count}, (_, i) => item(offset + i)),
    summary: {qrs_count: 206, interval_count: 205, total_intervals: 205, valid_rr_count: 205,
      invalid_rr_count: 0, unknown_count: 0, nn_eligible_count: 205, normal_pair_count: 205,
      rr_min_ms: 800, rr_max_ms: 800, hr_min_bpm: 75, hr_max_bpm: 75},
    histogram: {mode: query.mode || 'rr', unit: query.mode === 'hr' ? 'bpm' : query.mode === 'ratio' ? '%' : 'ms', bin_width: 20,
      bins: [{start: 780, end: 800, count: 0, overflow: false}, {start: 800, end: 820, count: total, overflow: false}]},
    pair_types: [{code: '["N","N"]', left_type: 'N', right_type: 'N', total: 205, valid_rr_count: 205, unknown_count: 0}],
    method_version: 'synthetic-v1', method: {rr: 'RR from consecutive retained source neighbors', ratio: 'RR(i)/RR(i-1)×100%',
      hr: '60000/RR', normal_pair: 'ordered N→N', nn: 'current NN eligibility', classification: 'current saved types',
      manual_review: 'manual type required', unknown: 'missing remains unknown'}, ...overrides};
}
function stripResponse(request) {
  const body = JSON.parse(request.options.body);
  return {...basis, case_id: CASE_ID, items: body.sample_indices.map(sample_index => ({case_id: CASE_ID, sample_index, sample_rate_hz: 200,
    duration_s: 4, anchor_offset_s: 1.5, stride: 1, leads: {II: [0, 1, 0], V1: [0, 0.5, 0], V5: [0, -1, 0]}}))};
}
function harness({current = () => true, onLocate = () => true, caseId = CASE_ID} = {}) {
  const host = new Element('section');
  const calls = [];
  const api = (raw, options = {}) => {
    const pending = deferred(), request = {url: new URL(raw, 'http://synthetic.invalid'), options, ...pending};
    calls.push(request);
    return pending.promise;
  };
  const document = {createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag),
    querySelector: selector => host.querySelector(selector), querySelectorAll: selector => host.querySelectorAll(selector)};
  const context = vm.createContext({document, URL, URLSearchParams, AbortController, console, setTimeout, clearTimeout,
    requestAnimationFrame: callback => callback(), cancelAnimationFrame() {}, devicePixelRatio: 1});
  vm.runInContext(fs.readFileSync(sourcePath, 'utf8'), context, {filename: sourcePath});
  assert(context.ECGRRReview && typeof context.ECGRRReview.mount === 'function', 'RR review module must export its mount interface');
  const controller = context.ECGRRReview.mount({host, caseId, basis: {...basis}, caseToken: 42, api, isCurrent: current, onLocate});
  for (const method of ['load', 'cancel', 'retry', 'dispose', 'snapshot']) assert.equal(typeof controller[method], 'function', 'missing controller.' + method);
  const role = name => host.querySelector(`[data-rr-role="${name}"]`);
  const action = (name, index) => host.querySelector(`[data-rr-action="${name}"]${index === undefined ? '' : `[data-rr-index="${index}"]`}`);
  return {host, calls, controller, role, action};
}

async function verifyRequestAndStaleQuery() {
  const h = harness();
  assert.equal(h.calls.length, 0, 'mount must wait for an explicit load');
  const first = h.controller.load({mode: 'rr', range_min: 700});
  await settle();
  assert.equal(h.calls.length, 1);
  const original = h.calls[0];
  assert.equal(original.url.pathname, '/api/cases/synthetic%20%2F%20RR/rr-review');
  for (const [key, value] of Object.entries(basis)) assert.equal(original.url.searchParams.get(key), String(value), 'request must pin ' + key);
  assert(original.options.signal instanceof AbortSignal, 'query must carry cancellation');
  const second = h.controller.load({mode: 'hr', range_min: 0, range_max: 200});
  await settle();
  assert.equal(h.calls.length, 2);
  assert(original.options.signal.aborted, 'a new query must abort the earlier request');
  h.calls[1].resolve(response(h.calls[1], {total: 12}));
  await second;
  assert.equal(h.controller.snapshot().phase, 'ready');
  assert.equal(h.controller.snapshot().total, 12);
  const current = plain(h.controller.snapshot()), html = h.host.innerHTML;
  original.resolve(response(original, {total: 77}));
  await first;
  assert.deepEqual(plain(h.controller.snapshot()), current, 'late old-filter response cannot overwrite current state');
  assert.equal(h.host.innerHTML, html, 'late old-filter response cannot replace current UI');
  h.controller.dispose();
}

async function verifyCaseAndDisposeGuards() {
  let active = true;
  const h = harness({current: () => active});
  const pending = h.controller.load();
  await settle();
  active = false;
  h.calls[0].resolve(response(h.calls[0], {total: 9}));
  await pending;
  assert.notEqual(h.controller.snapshot().phase, 'ready', 'a response from a departed case cannot become ready');
  assert.equal(h.host.querySelectorAll('[data-rr-action="locate"]').length, 0, 'departed case must have no actionable old target');
  h.controller.dispose();

  const disposed = harness(), job = disposed.controller.load();
  await settle();
  disposed.controller.dispose();
  assert(disposed.calls[0].options.signal.aborted, 'dispose aborts pending reads');
  const html = disposed.host.innerHTML;
  disposed.calls[0].resolve(response(disposed.calls[0], {total: 9}));
  await job;
  assert.equal(disposed.host.innerHTML, html, 'disposed view ignores completions');
}

async function verifyIdentityMismatches() {
  for (const [field, value] of [['analysis_basis', 'other-basis'], ['analysis_revision', 8], ['beat_revision', 4]]) {
    const h = harness(), job = h.controller.load();
    await settle();
    h.calls[0].resolve(response(h.calls[0], {[field]: value}));
    await job;
    assert.equal(h.controller.snapshot().phase, 'error', field + ' mismatch must block results');
    assert(h.controller.snapshot().error, field + ' mismatch needs a visible error');
    assert.equal(h.host.querySelectorAll('[data-rr-action="locate"]').length, 0, 'mismatched evidence has no locate targets');
    h.controller.dispose();
  }
}

async function verifyCaseIdentityMismatches() {
  const corruptions = [
    ['foreign response case', data => { data.case_id = 'synthetic-other-case'; }],
    ['missing response case', data => { delete data.case_id; }],
    ['foreign target case_id', data => { data.items[0].target.case_id = 'synthetic-other-case'; }],
    ['foreign target caseId', data => { data.items[0].target.caseId = 'synthetic-other-case'; }],
    ['foreign target both case aliases', data => { data.items[0].target.case_id = data.items[0].target.caseId = 'synthetic-other-case'; }],
    ['missing target case_id', data => { delete data.items[0].target.case_id; }],
    ['missing target caseId', data => { delete data.items[0].target.caseId; }],
    ['missing both target case aliases', data => { delete data.items[0].target.case_id; delete data.items[0].target.caseId; }],
  ];
  for (const [name, corrupt] of corruptions) {
    const located = [], h = harness({onLocate: target => { located.push(target); return true; }}), job = h.controller.load();
    await settle();
    const data = response(h.calls[0], {total: 1});
    corrupt(data);
    for (const [field, value] of Object.entries(basis)) assert.equal(data[field], value, name + ' keeps analysis identity unchanged');
    h.calls[0].resolve(data);
    await job;
    assert.equal(h.controller.snapshot().phase, 'error', name + ' must block a same-revision cross-case result');
    assert.equal(h.controller.snapshot().items.length, 0, name + ' must not expose interval rows');
    assert.equal(h.host.querySelectorAll('[data-rr-action="locate"]').length, 0, name + ' must not expose a locate action');
    assert.equal(located.length, 0);
    h.controller.dispose();
  }
}

async function verifyMalformedEvidenceIsBlocked() {
  const corruptions = [
    ['missing page member', data => { data.items.pop(); }],
    ['duplicate interval identity', data => { data.items[1].id = data.items[0].id; }],
    ['different target sample', data => { data.items[0].target.sample_index++; }],
    ['different target beat', data => { data.items[0].target.beat_id = 's:999999'; }],
    ['different target revision', data => { data.items[0].target.beat_revision++; }],
    ['different ordered pair echo', data => { data.query.pair_type = '["V","N"]'; }],
    ['unknown histogram count', data => { data.histogram.bins[0].count = null; }],
  ];
  for (const [name, corrupt] of corruptions) {
    const h = harness(), first = h.controller.load();
    await settle();
    h.calls[0].resolve(response(h.calls[0], {total: 2}));
    await first;
    assert.equal(h.controller.snapshot().phase, 'ready');
    const reload = h.controller.load();
    await settle();
    assert.equal(h.host.querySelectorAll('[data-rr-action="locate"]').length, 0, 'pending reload clears prior actionable targets');
    const data = response(h.calls[1], {total: 2});
    corrupt(data);
    h.calls[1].resolve(data);
    await reload;
    assert.equal(h.controller.snapshot().phase, 'error', name + ' must block the page');
    assert.equal(h.controller.snapshot().items.length, 0, name + ' must not retain stale results');
    assert.equal(h.host.querySelectorAll('[data-rr-action="locate"]').length, 0, name + ' must have no actionable target');
    h.controller.dispose();
  }
}

async function verifyEffectiveTimeWindowEcho() {
  const empty = harness(), job = empty.controller.load();
  await settle();
  const zero = response(empty.calls[0], {total: 0, items: [], duration_s: 0,
    histogram: {mode: 'rr', unit: 'ms', bin_width: 20, bins: []},
    summary: {qrs_count: 0, interval_count: 0, valid_rr_count: 0, invalid_count: 0, unknown_type_count: 0,
      normal_pair_count: 0, nn_eligible_count: 0, nn_candidate_count: 0, nn_verified_count: 0}});
  assert.equal(zero.query.start_s, 0);
  assert.equal(zero.query.end_s, 0);
  empty.calls[0].resolve(zero);
  await job;
  assert.equal(empty.controller.snapshot().phase, 'ready', 'a zero-duration empty record has a valid effective [0,0) query');
  assert.equal(empty.controller.snapshot().total, 0);
  assert.equal(empty.controller.snapshot().query.start_s, null, 'implicit UI bounds remain implicit after server normalization');
  assert.equal(empty.controller.snapshot().query.end_s, null);
  assert.equal(empty.role('summary').querySelectorAll('strong')[0].textContent, '0');
  assert.match(empty.role('results').textContent, /匹配 0 个间期/);
  empty.controller.dispose();

  for (const [name, patch, mutate, expected] of [
    ['explicit time range', {start_s: 10, end_s: 30}, () => {}, 'ready'],
    ['mismatched explicit start', {start_s: 10, end_s: 30}, data => { data.query.start_s = 11; }, 'error'],
    ['mismatched explicit end', {start_s: 10, end_s: 30}, data => { data.query.end_s = 31; }, 'error'],
    ['mismatched implicit full-record end', {}, data => { data.query.end_s = 900; }, 'error'],
  ]) {
    const h = harness(), load = h.controller.load(patch);
    await settle();
    const data = response(h.calls[0], {total: 0, items: []});
    mutate(data);
    h.calls[0].resolve(data);
    await load;
    assert.equal(h.controller.snapshot().phase, expected, name + ' must be validated against effective bounds');
    if (expected === 'error') assert.equal(h.controller.snapshot().items.length, 0);
    h.controller.dispose();
  }
}

async function verifyCancelAndRetry() {
  const h = harness(), original = h.controller.load({mode: 'ratio', range_min: 80, range_max: 120, limit: 20});
  await settle();
  h.controller.cancel();
  assert(h.calls[0].options.signal.aborted, 'cancel aborts active read');
  assert.equal(h.controller.snapshot().phase, 'cancelled');
  const savedQuery = plain(h.controller.snapshot().query);
  const retry = h.controller.retry();
  await settle();
  assert.equal(h.calls.length, 2);
  assert.deepEqual(plain(h.controller.snapshot().query), savedQuery, 'retry must retain the cancelled query');
  h.calls[1].resolve(response(h.calls[1], {total: 2}));
  await retry;
  const current = plain(h.controller.snapshot());
  h.calls[0].resolve(response(h.calls[0], {total: 13}));
  await original;
  assert.deepEqual(plain(h.controller.snapshot()), current, 'cancelled completion cannot overwrite retry');
  h.controller.dispose();

  const offline = harness(), failed = offline.controller.load({pair_type: '["N","V"]', population: 'all'});
  await settle();
  offline.calls[0].reject(Error('synthetic offline failure'));
  await failed;
  assert.equal(offline.controller.snapshot().phase, 'error');
  assert.match(offline.controller.snapshot().error, /synthetic offline failure/);
  assert(offline.action('retry'), 'error view offers retry');
  offline.action('retry').click();
  await settle();
  assert.equal(offline.calls.length, 2, 'retry button performs a fresh read');
  assert.equal(offline.calls[1].url.searchParams.get('pair_type'), '["N","V"]');
  offline.calls[1].resolve(response(offline.calls[1], {total: 0, items: []}));
  await settle();
  assert.equal(offline.controller.snapshot().phase, 'ready');
  assert.equal(offline.controller.snapshot().total, 0, 'verified empty population preserves real zero');
  offline.controller.dispose();
}

async function verifyPagingAndExactTargets() {
  const located = [], h = harness({onLocate: target => { located.push(plain(target)); return true; }});
  const initial = h.controller.load({limit: 100});
  await settle();
  h.calls[0].resolve(response(h.calls[0]));
  await initial;
  const seen = new Set(h.controller.snapshot().items.map(row => row.target.sample_index));
  assert.equal(h.controller.snapshot().total, 205, 'full count cannot collapse to visible page size');
  assert.equal(h.controller.snapshot().items.length, 100);
  assert(h.action('next') && !h.action('next').disabled);
  h.action('locate', 0).click();
  await settle();
  assert.equal(located.length, 1);
  assert.deepEqual(located[0], {...item(0).target, case_id: 'synthetic / RR', case_token: 42}, 'locate forwards exact sample and complete scope');
  for (const [page, offset, count] of [[1, 100, 100], [2, 200, 5]]) {
    h.action('next').click();
    await settle();
    assert.equal(h.calls.length, page + 1);
    assert.equal(h.calls[page].url.searchParams.get('offset'), String(offset));
    h.calls[page].resolve(response(h.calls[page]));
    await settle();
    assert.equal(h.controller.snapshot().offset, offset);
    assert.equal(h.controller.snapshot().items.length, count, 'last page must retain its remainder');
    assert.equal(h.controller.snapshot().total, 205);
    for (const row of h.controller.snapshot().items) seen.add(row.target.sample_index);
  }
  assert.equal(seen.size, 205, 'every matching interval is reachable without truncation');
  assert(!h.action('next') || h.action('next').disabled, 'last page disables forward navigation');
  h.action('locate', 4).click();
  await settle();
  assert.equal(located.at(-1).sample_index, item(204).target.sample_index, 'last result locates its original sample');
  h.action('previous').click();
  await settle();
  assert.equal(h.calls[3].url.searchParams.get('offset'), '100');
  h.calls[3].resolve(response(h.calls[3]));
  await settle();
  h.controller.dispose();
}

async function verifyFiltersAndLocationRaces() {
  let locationGuard;
  const location = deferred(), h = harness({onLocate: (_, guard) => { locationGuard = guard; return location.promise; }});
  const initial = h.controller.load({mode: 'rr', range_min: 700, range_max: 900, offset: 100, limit: 100});
  await settle();
  h.calls[0].resolve(response(h.calls[0]));
  await initial;
  h.action('locate', 0).click();
  await settle();
  assert(locationGuard.signal instanceof AbortSignal, 'exact locate gets a cancellable guard');
  assert.equal(locationGuard.isCurrent(), true);
  const changed = h.controller.load({pair_type: '["N","V"]'});
  await settle();
  assert(locationGuard.signal.aborted, 'new query aborts the earlier exact locate');
  assert.equal(locationGuard.isCurrent(), false, 'old locate guard rejects a changed query');
  assert.equal(h.calls[1].url.searchParams.get('offset'), '0', 'new type filter starts at the first result');
  assert.equal(h.calls[1].url.searchParams.get('range_min'), '700', 'type change retains the current metric range');
  h.calls[1].resolve(response(h.calls[1], {total: 2}));
  await changed;
  const html = h.host.innerHTML, snapshot = plain(h.controller.snapshot());
  location.resolve({located: true});
  await settle();
  assert.equal(h.host.innerHTML, html, 'late locate completion cannot annotate a different query');
  assert.deepEqual(plain(h.controller.snapshot()), snapshot);
  const mode = h.controller.load({mode: 'hr'});
  await settle();
  assert.equal(h.calls[2].url.searchParams.has('range_min'), false, 'metric change clears a range expressed in the old unit');
  assert.equal(h.calls[2].url.searchParams.has('range_max'), false);
  h.calls[2].resolve(response(h.calls[2], {total: 0, items: []}));
  await mode;
  h.controller.dispose();

  let invalidTarget;
  const failed = harness({onLocate: target => { invalidTarget = plain(target); return {located: false, reason: 'synthetic target removed; not located'}; }});
  const ready = failed.controller.load();
  await settle();
  failed.calls[0].resolve(response(failed.calls[0], {total: 1}));
  await ready;
  failed.action('locate', 0).click();
  await settle();
  assert.equal(invalidTarget.sample_index, item(0).target.sample_index, 'failed locate still requests the exact target');
  assert.match(failed.role('status').textContent, /synthetic target removed; not located/, 'failure is shown instead of an apparent successful neighbor');
  assert(!failed.role('status').textContent.includes('已精确定位'));
  assert.equal(failed.host.querySelectorAll('[aria-selected="true"]').length, 0);
  failed.controller.dispose();
}

async function verifyLocateGuardAndAcknowledgement() {
  const pending = [], h = harness({onLocate: (target, guard) => {
    const job = deferred(); pending.push({target: plain(target), guard, ...job}); return job.promise;
  }});
  const ready = h.controller.load();
  await settle();
  h.calls[0].resolve(response(h.calls[0], {total: 2}));
  await ready;
  h.action('locate', 0).click();
  await settle();
  h.action('locate', 1).click();
  await settle();
  assert(pending[0].guard.signal.aborted, 'next locate cancels the previous location request');
  assert.equal(pending[0].guard.isCurrent(), false);
  assert.equal(pending[1].guard.isCurrent(), true);
  pending[0].resolve({located: true});
  await settle();
  assert(!h.role('status').textContent.includes('已精确定位'), 'superseded locate cannot claim success');
  pending[1].resolve({located: true});
  await settle();
  assert.match(h.role('status').textContent, new RegExp('已精确定位终搏样本 ' + item(1).target.sample_index));
  h.action('locate', 0).click();
  await settle();
  h.controller.cancel();
  assert(pending[2].guard.signal.aborted, 'cancel aborts location work');
  assert.equal(pending[2].guard.isCurrent(), false);
  pending[2].resolve({located: true});
  await settle();
  assert.equal(h.controller.snapshot().phase, 'cancelled');
  const retry = h.controller.retry();
  await settle();
  h.calls[1].resolve(response(h.calls[1], {total: 2}));
  await retry;
  h.action('locate', 0).click();
  await settle();
  h.controller.dispose();
  assert(pending[3].guard.signal.aborted, 'dispose aborts exact location work');
  assert.equal(pending[3].guard.isCurrent(), false);
  pending[3].resolve({located: true});
  await settle();
  assert.equal(h.host.innerHTML, '', 'disposed location completion cannot recreate the UI');

  const unacknowledged = harness({onLocate: () => undefined}), load = unacknowledged.controller.load();
  await settle();
  unacknowledged.calls[0].resolve(response(unacknowledged.calls[0], {total: 1}));
  await load;
  unacknowledged.action('locate', 0).click();
  await settle();
  assert.match(unacknowledged.role('status').textContent, /等待波形核对/, 'unacknowledged request waits for waveform verification');
  assert(!unacknowledged.role('status').textContent.includes('已精确定位'), 'undefined location response cannot claim an exact location');
  assert.equal(unacknowledged.host.querySelectorAll('[aria-selected="true"]').length, 0, 'unverified locate cannot mark a row as successfully located');
  unacknowledged.controller.dispose();
}

async function verifyExactOptionalStrips() {
  const h = harness(), ready = h.controller.load({limit: 20});
  await settle();
  h.calls[0].resolve(response(h.calls[0], {total: 20}));
  await ready;
  assert.equal(h.calls.length, 1, 'unchecked strips must not issue waveform reads');
  const toggle = h.host.querySelector('[data-rr-field="strips"]');
  toggle.checked = true;
  toggle.dispatchEvent({type: 'change', bubbles: true});
  await settle();
  const seen = [];
  for (let batchIndex = 1; batchIndex <= 2; batchIndex++) {
    const request = h.calls[batchIndex];
    assert(request, 'every current-page waveform batch must be requested');
    assert.equal(request.url.pathname, '/api/cases/synthetic%20%2F%20RR/waveform-strips');
    assert.equal(request.options.method, 'POST');
    const body = JSON.parse(request.options.body);
    assert.equal(body.case_id, CASE_ID, 'strip request pins the exact case');
    assert.deepEqual(body.leads, ['II', 'V1', 'V5']);
    for (const [name, value] of Object.entries(basis)) assert.equal(body[name], value, 'strips pin ' + name);
    assert.equal(body.revision, basis.beat_revision);
    assert.equal(body.sample_indices.length, batchIndex === 1 ? 16 : 4, 'batching cannot truncate the page');
    seen.push(...body.sample_indices);
    request.resolve(stripResponse(request));
    await settle();
  }
  assert.deepEqual(seen, Array.from({length: 20}, (_, i) => item(i).target.sample_index), 'waveform requests preserve the exact current-page sample set');
  assert.equal(h.controller.snapshot().stripsPhase, 'ready');
  assert.equal(h.host.querySelectorAll('canvas[data-rr-strip]').length, 20, 'all current-page excerpts render');
  toggle.checked = false;
  toggle.dispatchEvent({type: 'change', bubbles: true});
  assert.equal(h.host.querySelectorAll('canvas[data-rr-strip]').length, 0);
  toggle.checked = true;
  toggle.dispatchEvent({type: 'change', bubbles: true});
  await settle();
  const abandoned = h.calls[3];
  toggle.checked = false;
  toggle.dispatchEvent({type: 'change', bubbles: true});
  assert(abandoned.options.signal.aborted, 'hiding strips aborts the pending waveform request');
  toggle.checked = true;
  toggle.dispatchEvent({type: 'change', bubbles: true});
  await settle();
  for (const index of [4, 5]) { h.calls[index].resolve(stripResponse(h.calls[index])); await settle(); }
  assert.equal(h.controller.snapshot().stripsPhase, 'ready');
  const before = h.host.innerHTML;
  abandoned.resolve(stripResponse(abandoned));
  await settle();
  assert.equal(h.controller.snapshot().stripsPhase, 'ready', 'late off→on completion cannot reset the new strip state');
  assert.equal(h.host.innerHTML, before, 'late off→on completion cannot overwrite newly loaded excerpts');
  assert.equal(h.calls.length, 6, 'aborted old batch does not continue into a second batch');
  toggle.checked = false;
  toggle.dispatchEvent({type: 'change', bubbles: true});
  toggle.checked = true;
  toggle.dispatchEvent({type: 'change', bubbles: true});
  await settle();
  const oldQueryStrip = h.calls[6];
  const newQuery = h.controller.load({mode: 'hr'});
  await settle();
  assert(oldQueryStrip.options.signal.aborted, 'a new query aborts waveform work from the old result set');
  oldQueryStrip.resolve(stripResponse(oldQueryStrip));
  await settle();
  assert.equal(h.controller.snapshot().phase, 'loading');
  assert.equal(h.host.querySelectorAll('canvas[data-rr-strip]').length, 0, 'old waveform completion cannot repopulate a pending new query');
  h.calls[7].resolve(response(h.calls[7], {total: 0, items: []}));
  await newQuery;
  await settle();
  assert.equal(h.calls.length, 8, 'old waveform completion does not continue after a query switch');
  assert.equal(h.controller.snapshot().total, 0);
  h.controller.dispose();
}

async function verifyMalformedStripsAreBlocked() {
  const corruptions = [
    ['incomplete waveform set', data => { data.items.pop(); }],
    ['mismatched waveform sample', data => { data.items[0].sample_index++; }],
    ['mismatched waveform basis', data => { data.analysis_basis = 'foreign synthetic basis'; }],
    ['mismatched waveform beat revision', data => { data.beat_revision++; }],
    ['missing waveform response case', data => { delete data.case_id; }],
    ['foreign waveform response case', data => { data.case_id = 'synthetic-other-case'; }],
    ['missing waveform item case', data => { delete data.items[0].case_id; }],
    ['foreign waveform item case', data => { data.items[0].case_id = 'synthetic-other-case'; }],
  ];
  for (const [name, corrupt] of corruptions) {
    const h = harness(), job = h.controller.load({limit: 20});
    await settle();
    h.calls[0].resolve(response(h.calls[0], {total: 2}));
    await job;
    const toggle = h.host.querySelector('[data-rr-field="strips"]');
    toggle.checked = true;
    toggle.dispatchEvent({type: 'change', bubbles: true});
    await settle();
    const data = stripResponse(h.calls[1]);
    corrupt(data);
    h.calls[1].resolve(data);
    await settle();
    assert.equal(h.controller.snapshot().stripsPhase, 'error', name + ' must block all excerpts');
    assert.equal(h.host.querySelectorAll('canvas[data-rr-strip]').length, 0, name + ' must not draw an inaccurate excerpt');
    assert.equal(h.controller.snapshot().phase, 'ready', 'waveform failure preserves the verified interval result set');
    assert.equal(h.controller.snapshot().items.length, 2);
    assert.match(h.role('status').textContent, /读取失败/);
    h.controller.dispose();
  }
}

async function verifyChartInteractions() {
  const h = harness(), job = h.controller.load();
  await settle();
  const histogram = {mode: 'rr', unit: 'ms', bin_width: 20, bins: [
    {start: 780, end: 800, count: 0, overflow: false},
    {start: 800, end: 820, count: 1, overflow: false},
    {start: 820, end: null, count: 1, overflow: true},
  ]};
  const data = response(h.calls[0], {total: 2, histogram});
  const originalHistogram = JSON.stringify(histogram);
  h.calls[0].resolve(data);
  await job;
  const snapshot = plain(h.controller.snapshot()), trueCount = h.role('chart-count').textContent;
  const log = h.host.querySelector('[data-rr-field="log"]');
  log.checked = true;
  log.dispatchEvent({type: 'change', bubbles: true});
  assert.match(h.role('histogram').getAttribute('aria-description'), /对数计数显示/);
  assert.deepEqual(plain(h.controller.snapshot()), snapshot, 'log display cannot change result membership or counts');
  assert.equal(h.role('chart-count').textContent, trueCount, 'log display retains the real count');
  assert.equal(JSON.stringify(data.histogram), originalHistogram, 'log display cannot mutate histogram data');
  assert.equal(h.calls.length, 1, 'log display is a view operation');
  log.checked = false;
  log.dispatchEvent({type: 'change', bubbles: true});
  assert.match(h.role('histogram').getAttribute('aria-description'), /线性计数显示/);

  const canvas = h.role('histogram'), geometry = canvas._rrGeometry;
  const point = bin => ({clientX: geometry.left + (bin + 0.5) * geometry.width / 3,
    clientY: geometry.top + 10, pointerId: 9, bubbles: true});
  canvas.dispatchEvent({type: 'pointerdown', ...point(0)});
  canvas.dispatchEvent({type: 'pointermove', ...point(1)});
  assert.match(h.role('selection').textContent, /\[780, 820\)/, 'pointer preview shows the complete selected bin range');
  assert.match(h.role('selection').textContent, /1 个/, 'pointer preview reports real bin counts');
  canvas.dispatchEvent({type: 'pointerup', ...point(1)});
  await settle();
  assert.equal(h.calls[1].url.searchParams.get('range_min'), '780');
  assert.equal(h.calls[1].url.searchParams.get('range_max'), '820');
  assert.equal(h.calls[1].url.searchParams.get('offset'), '0');
  h.calls[1].resolve(response(h.calls[1], {total: 1, histogram}));
  await settle();

  canvas.dispatchEvent({type: 'keydown', key: 'Home', bubbles: true});
  canvas.dispatchEvent({type: 'keydown', key: 'ArrowRight', shiftKey: true, bubbles: true});
  assert.match(h.role('selection').textContent, /\[780, 820\)/, 'Shift preview shows the complete expanded range');
  assert.match(h.role('selection').textContent, /1 个/, 'Shift preview reports the real summed count');
  canvas.dispatchEvent({type: 'keydown', key: 'Enter', bubbles: true});
  await settle();
  assert.equal(h.calls[2].url.searchParams.get('range_min'), '780', 'Shift expands from the original keyboard anchor');
  assert.equal(h.calls[2].url.searchParams.get('range_max'), '820', 'Enter applies the complete keyboard range');
  h.calls[2].resolve(response(h.calls[2], {total: 1, histogram}));
  await settle();

  canvas.dispatchEvent({type: 'keydown', key: 'End', bubbles: true});
  canvas.dispatchEvent({type: 'keydown', key: 'Enter', bubbles: true});
  await settle();
  assert.equal(h.calls[3].url.searchParams.get('range_min'), '820');
  assert.equal(h.calls[3].url.searchParams.has('range_max'), false, 'overflow bin uses an open upper bound');
  assert.equal(h.controller.snapshot().query.range_max, null, 'overflow remains unbounded in query state');
  h.calls[3].resolve(response(h.calls[3], {total: 1, histogram}));
  await settle();

  canvas.dispatchEvent({type: 'keydown', key: 'Escape', bubbles: true});
  await settle();
  assert.equal(h.calls[4].url.searchParams.has('range_min'), false, 'Escape clears the selected lower bound');
  assert.equal(h.calls[4].url.searchParams.has('range_max'), false, 'Escape clears the selected upper bound');
  h.calls[4].resolve(response(h.calls[4], {total: 2, histogram}));
  await settle();
  assert.equal(h.controller.snapshot().total, 2);
  h.controller.dispose();
}

async function verifyZeroNullAndEscaping() {
  const h = harness(), job = h.controller.load({limit: 20});
  await settle();
  const synthetic = item(0, {rr_ms: 0, ratio_pct: null, hr_bpm: 0, left_type: '<script>synthetic</script>', right_type: '<img src=x>',
    right: {...item(0).right, id: '<unsafe-beat>'}, target: {...item(0).target, beat_id: '<unsafe-beat>'}});
  h.calls[0].resolve(response(h.calls[0], {total: 1, items: [synthetic], summary: {qrs_count: 0, interval_count: null,
    total_intervals: null, valid_rr_count: 0, invalid_rr_count: null, unknown_count: 0, nn_eligible_count: null}}));
  await job;
  const results = h.role('results');
  assert(results, 'result region exists');
  const cells = results.querySelector('tbody tr').querySelectorAll('td');
  assert.equal(cells[2].textContent, '0', 'true zero RR metric must be visible');
  assert.equal(cells[3].textContent, '—', 'missing ratio must remain visibly unavailable');
  assert.equal(cells[4].textContent, '0', 'true zero HR metric must be visible');
  const summaries = h.role('summary').querySelectorAll('strong');
  assert.equal(summaries[0].textContent, '0', 'true zero QRS summary is preserved');
  assert.equal(summaries[1].textContent, '未知', 'missing interval summary is not a zero');
  assert(!/NaN|Infinity|undefined|null/.test(results.textContent), 'missing values must not leak numeric coercion or literals');
  assert.equal(h.host.querySelectorAll('script').length, 0, 'type labels must be HTML escaped');
  assert.equal(h.host.querySelectorAll('img').length, 0, 'type labels must not become markup');
  assert(h.host.innerHTML.includes('&lt;script&gt;'), 'escaped source type stays reviewable');
  h.controller.dispose();
}

async function verifyAllInvalidWithoutTargets() {
  const located = [], h = harness({onLocate: target => { located.push(target); return true; }}), job = h.controller.load({quality: 'invalid'});
  await settle();
  const samples = [[200, 200], [600, 400], [null, 'invalid-sample']];
  const items = samples.map(([start_sample, end_sample], index) => item(index, {id: 'synthetic-invalid:' + index,
    start_sample, end_sample, left: {id: 'invalid-left:' + index, sample_index: start_sample},
    right: {id: 'invalid-right:' + index, sample_index: end_sample}, target: null,
    rr_ms: null, computed_rr_ms: [0, -1000, null][index], stored_rr_ms: [800, 900, null][index], ratio_pct: null, hr_bpm: null, time_s: null, nn_eligible_current_rules: false,
    quality: {valid: false, reason: ['duplicate sample', 'reversed samples', 'missing sample'][index]}, nn_reason: 'invalid RR'}));
  h.calls[0].resolve(response(h.calls[0], {total: 3, items, histogram: {mode: 'rr', unit: 'ms', bin_width: 20, bins: []},
    summary: {qrs_count: 4, interval_count: 3, valid_rr_count: 0, invalid_count: 3, unknown_type_count: 0,
      normal_pair_count: 3, nn_eligible_count: 0, nn_candidate_count: 0, nn_verified_count: 0}}));
  await job;
  assert.equal(h.controller.snapshot().phase, 'ready', 'verified invalid rows remain reviewable');
  assert.equal(h.controller.snapshot().total, 3, 'invalid targets do not reduce the full matched population');
  assert.equal(h.controller.snapshot().items.length, 3);
  assert(h.controller.snapshot().items.every(row => row.target === null));
  assert.equal(h.role('results').querySelectorAll('tbody tr').length, 3, 'every invalid row is retained');
  for (const [index, row] of h.role('results').querySelectorAll('tbody tr').entries()) {
    const cells = row.querySelectorAll('td');
    assert.match(cells[2].textContent, /^—/, 'invalid physiological RR stays unavailable');
    if (index < 2) {
      assert.match(cells[2].textContent, /采样间距.*ms/, 'finite computed sample spacing remains reviewable');
      assert.match(cells[2].textContent, /输入间期/, 'stored RR is labelled current input interval');
    } else assert.equal(cells[2].textContent, '—');
    assert.equal(cells[3].textContent, '—');
    assert.equal(cells[4].textContent, '—');
    assert.match(cells[6].textContent, /目标不可用/);
  }
  assert.equal(h.role('summary').querySelectorAll('strong')[2].textContent, '0', 'no valid RR remains an explicit zero');
  assert(h.host.querySelectorAll('[data-rr-action="locate"]').every(button => button.disabled), 'null targets cannot offer actionable location');
  for (const button of h.host.querySelectorAll('[data-rr-action="locate"]')) button.click();
  await settle();
  assert.equal(located.length, 0, 'unavailable exact targets never call location');
  const strips = h.host.querySelector('[data-rr-field="strips"]');
  strips.checked = true;
  strips.dispatchEvent({type: 'change', bubbles: true});
  await settle();
  assert.equal(h.calls.length, 1, 'null targets do not request nearest-neighbor waveform excerpts');
  assert.equal(h.host.querySelectorAll('canvas[data-rr-strip]').length, 0);
  assert.equal(h.controller.snapshot().total, 3);
  h.controller.dispose();

  const valid = harness(), load = valid.controller.load();
  await settle();
  valid.calls[0].resolve(response(valid.calls[0], {total: 1, items: [item(0, {target: null})]}));
  await load;
  assert.equal(valid.controller.snapshot().phase, 'error', 'a valid-quality row cannot silently omit an exact target');
  valid.controller.dispose();
}

async function verifyReadableClinicalEvidence() {
  const reasonCodes = ['artifact_boundary', 'flutter_no_ordinary_rr', 'unknown_type', 'outside_current_nn_bounds',
    'excluded_rhythm_interval', 'missing_stored_rr', 'stored_sample_mismatch', 'outside_recording',
    'invalid_sample', 'non_increasing_samples', 'duplicate_sample', 'unrecognized_synthetic_reason'];
  const h = harness(), job = h.controller.load();
  await settle();
  const items = reasonCodes.flatMap((code, index) => [
    item(index * 2, {quality: {valid: false, reason: code}, nn_reason: code, target: null,
      nn_eligible_current_rules: false, nn_eligible_verified: false}),
    item(index * 2 + 1, {quality: {valid: true, reason: null}, nn_reason: code,
      nn_eligible_current_rules: false, nn_eligible_verified: false}),
  ]);
  items.push(item(items.length, {nn_eligible_current_rules: true, nn_eligible_verified: false}));
  items.push(item(items.length, {nn_eligible_current_rules: true, nn_eligible_verified: true}));
  for (const row of items) {
    row.left = {...row.left, classification_source: 'physician_override'};
    row.right = {...row.right, classification_source: 'physician_position_edit'};
  }
  const references = ['https://physionet.org/physiotools/wag/ann2rr-1.htm',
    'https://physionet.org/content/wfdb/10.7.0/lib/ecgmap.h'];
  h.calls[0].resolve(response(h.calls[0], {total: items.length, items, method: {
    nn_settings_known: true, duration_known: false, hospital_mapping_verified: false, references,
  }}));
  await job;
  assert.equal(h.controller.snapshot().phase, 'ready');
  const rows = h.role('results').querySelectorAll('tbody tr');
  assert.equal(rows.length, items.length);
  for (const [index, code] of reasonCodes.entries()) {
    for (const variant of [0, 1]) {
      const row = rows[index * 2 + variant], cells = row.querySelectorAll('td'), reason = cells[5].textContent;
      assert(!row.textContent.includes(code), code + ' must not be a visible product label');
      assert(row.querySelectorAll('[title]').some(node => node.getAttribute('title').includes(code)), code + ' remains available in a title');
      assert.match(reason, /NN 候选未通过/, 'candidate=false must explain why it did not pass');
      if (code === 'unrecognized_synthetic_reason') assert.match(reason, /原因未说明/, 'unknown reason codes get a readable fallback');
      else {
        assert(/[\u3400-\u9fff]/.test(reason), code + ' must have a Chinese explanation');
        assert(!reason.includes('原因未说明'), code + ' must have a known explanation instead of the fallback');
      }
      assert.match(cells[1].textContent, /人工覆盖\s*→\s*位置修订/, 'new physician source codes have readable labels');
      assert(!cells[1].textContent.includes('physician_override'));
      assert(!cells[1].textContent.includes('physician_position_edit'));
      assert(cells[1].querySelectorAll('[title]').some(node => node.getAttribute('title').includes('physician_override')));
      assert(cells[1].querySelectorAll('[title]').some(node => node.getAttribute('title').includes('physician_position_edit')));
    }
  }
  const candidate = rows[reasonCodes.length * 2].querySelectorAll('td')[5].textContent;
  assert.match(candidate, /NN 候选\s*·\s*窦性未核实/, 'candidate eligibility does not imply verified sinus rhythm');
  assert(!candidate.includes('已核实 NN'));
  assert.match(rows[reasonCodes.length * 2 + 1].querySelectorAll('td')[5].textContent, /已核实 NN/);
  const method = h.role('provenance');
  assert.match(method.textContent, /NN 候选范围已知\s*是/);
  assert.match(method.textContent, /记录时长已知\s*否/);
  assert.match(method.textContent, /医院映射已核实\s*否/);
  assert(!/\btrue\b|\bfalse\b/.test(method.textContent), 'boolean method facts are readable Chinese values');
  const links = method.querySelectorAll('a');
  assert.deepEqual(links.map(link => link.getAttribute('href')), references, 'official method references render as links');
  assert(!method.textContent.includes('["https://'), 'reference arrays must not be exposed as JSON');
  assert.match(links[0].textContent, /RR\s*间期定义/);
  assert.match(links[1].textContent, /注释类型映射/);
  h.controller.dispose();
}

async function verify() {
  await verifyRequestAndStaleQuery();
  await verifyCaseAndDisposeGuards();
  await verifyIdentityMismatches();
  await verifyCaseIdentityMismatches();
  await verifyMalformedEvidenceIsBlocked();
  await verifyEffectiveTimeWindowEcho();
  await verifyCancelAndRetry();
  await verifyPagingAndExactTargets();
  await verifyFiltersAndLocationRaces();
  await verifyLocateGuardAndAcknowledgement();
  await verifyExactOptionalStrips();
  await verifyMalformedStripsAreBlocked();
  await verifyChartInteractions();
  await verifyZeroNullAndEscaping();
  await verifyAllInvalidWithoutTargets();
  await verifyReadableClinicalEvidence();
  console.log('RR review offline: pinned evidence, stale-query/case/dispose guards, malformed-result rejection, cancel/retry, zero/null, 205-result pagination, exact locate races, batched exact strips, pointer/keyboard/overflow/log chart controls and escaping passed');
}

module.exports = {Element, TextNode, harness, response, item, verify};
if (require.main === module) verify().catch(error => { console.error(error); process.exitCode = 1; });
