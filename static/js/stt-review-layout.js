/* Read-only ST-T context. The caller supplies the existing measurement results. */
(function (global) {
  'use strict';
  const number = value => typeof value === 'number' && Number.isFinite(value) ? value : null;
  const escape = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const time = value => {
    if (number(value) === null || value < 0) return '—';
    const milliseconds = Math.round(value * 1000), seconds = Math.floor(milliseconds / 1000);
    return `D${Math.floor(seconds / 86400) + 1} ${String(Math.floor(seconds / 3600) % 24).padStart(2, '0')}:${String(Math.floor(seconds / 60) % 60).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}.${String(milliseconds % 1000).padStart(3, '0')}`;
  };
  const pointLabel = value => value === 0 ? 'J 点' : number(value) !== null ? `J+${value} ms` : '测量点未提供';
  function context(snapshot) {
    const source = snapshot || {}, start = number(source.start_s), duration = number(source.duration_s);
    const ready = source.status === 'ready' && Boolean(source.caseId) && start !== null && start >= 0 && duration !== null && duration > 0;
    if (!ready) {
      const navigation=source.navigation, navStart=number(navigation?.start_s), navDuration=number(navigation?.duration_s), total=number(navigation?.total_s);
      const canNavigate=Boolean(source.caseId)&&navStart!==null&&navStart>=0&&navDuration!==null&&navDuration>0&&total!==null&&total>0;
      return {ready:false,canNavigate,status:['loading','cancelled','error','empty'].includes(source.status) ? source.status : 'empty',
        message:String(source.message || '尚无当前波形，请选择时间窗读取。'),start:navStart,duration:navDuration,total,
        window:canNavigate?`${time(navStart)}–${time(navStart+navDuration)}`:null,
        leads:Array.isArray(source.leadNames)?source.leadNames.filter(lead=>typeof lead==='string'&&lead.length<=12):[],pointLabel:pointLabel(source.measurementMs)};
    }
    const leads = Array.isArray(source.leadNames) ? source.leadNames.filter(lead => typeof lead === 'string' && lead.length <= 12) : [];
    const at = key => {
      const fraction = number(source.landmarks?.[key]);
      return fraction !== null && fraction >= 0 && fraction <= 1 ? time(start + fraction * duration) : '—';
    };
    const values = Array.isArray(source.measurements) ? source.measurements : [];
    return {
      ready:true, canNavigate:true, status:'ready', window:`${time(start)}–${time(start + duration)}`, leads,
      iso:at('iso'), j:at('j'), point:at('st'), pointLabel:pointLabel(source.measurementMs),
      mode:source.automaticEnabled === true ? '机器候选 · 待医生复核' : '仅人工复核',
      measurements:leads.map(lead => ({lead, delta:number(values.find(item => item?.lead === lead)?.delta)})),
      start, duration, total:number(source.total_s),
    };
  }
  function markup(model) {
    if (!model.ready) return `${model.window?`<div class="stt-context-heading"><strong>所选窗口 · 待读取</strong><span>${escape(model.pointLabel)}</span></div><div class="stt-context-window"><span>${escape(model.window)}</span><strong>${escape(model.leads.join(' / '))}</strong></div>`:''}<p class="stt-context-state">${escape(model.message)}</p>`;
    return `<div class="stt-context-heading"><strong>当前测量对象</strong><span>${escape(model.mode)}</span></div>
      <div class="stt-context-window"><span>${escape(model.window)}</span><strong>${escape(model.leads.join(' / ') || '导联未提供')}</strong></div>
      <dl class="stt-context-landmarks"><div><dt>ISO · 基线</dt><dd>${escape(model.iso)}</dd></div><div><dt>J · 游标</dt><dd>${escape(model.j)}</dd></div><div><dt>${escape(model.pointLabel)} · 测量点</dt><dd>${escape(model.point)}</dd></div></dl>
      <div class="stt-context-values" aria-label="当前导联手工相对差值">${model.measurements.map(item => `<span><strong>${escape(item.lead)}</strong> ${item.delta === null ? '—' : `${item.delta >= 0 ? '+' : ''}${item.delta.toFixed(0)}`} <small>设备单位</small></span>`).join('')}<small>ISO → ${escape(model.pointLabel)} · 幅值未校准</small></div>`;
  }
  function mount(options = {}) {
    const root = options.root, host = root?.querySelector('#sttCurrentContext');
    const status=root?.querySelector('#sttAnalysisStatus'),card=root?.querySelector('.stt-waveform-card');
    if(status&&card&&host&&status.parentElement!==card)card.insertBefore(status,host);
    let model = context(null);
    const locate = options.onLocate;
    const trackFrom = event => {
      const track = event.target?.closest?.('.stt-trend-track');
      return track && root?.contains(track) && track.getAttribute('role') === 'button' ? track : null;
    };
    const leadOf = track => track.parentElement?.querySelector('strong')?.textContent?.trim() || '';
    const navigate = (track, seconds) => {
      if (!model.canNavigate || model.total === null || model.total <= 0 || typeof locate !== 'function') return;
      locate({time_s:Math.max(0, Math.min(model.total, seconds)), lead:leadOf(track)});
    };
    const click = event => {
      const track = trackFrom(event);
      if (!track || !model.canNavigate || model.total === null) return;
      const rect = track.getBoundingClientRect();
      if (rect.width > 0) navigate(track, (event.clientX - rect.left) / rect.width * model.total);
    };
    const keydown = event => {
      const track = trackFrom(event);
      if (!track || event.ctrlKey || event.metaKey || event.altKey || !['ArrowLeft','ArrowRight','Enter',' '].includes(event.key)) return;
      if (!model.canNavigate) return;
      event.preventDefault();
      navigate(track, model.start + model.duration / 2 + (event.key === 'ArrowLeft' ? -16 : event.key === 'ArrowRight' ? 16 : 0));
    };
    root?.addEventListener('click', click);
    root?.addEventListener('keydown', keydown);
    function render(snapshot) {
      model = context(snapshot);
      if (host) {host.dataset.state = model.status; host.innerHTML = markup(model);}
      root?.classList.toggle('stt-review-layout', Boolean(host));
      root?.querySelectorAll('.stt-trend-track').forEach(track => {
        if (model.canNavigate && typeof locate === 'function' && model.total !== null && model.total > 0) {
          track.setAttribute('role', 'button');
          track.setAttribute('tabindex', '0');
          track.setAttribute('aria-label', `${leadOf(track)} ST 趋势定位；左右方向键移动 16 秒`);
          track.setAttribute('title', '点击定位原始波形；左右方向键移动 16 秒');
        } else {
          for (const name of ['role','tabindex','aria-label','title']) track.removeAttribute(name);
        }
      });
      return model;
    }
    return {
      render,
      clear(message, status = 'loading') {return render({status, message});},
      destroy() {root?.removeEventListener('click', click); root?.removeEventListener('keydown', keydown); render(null); root?.classList.remove('stt-review-layout');},
    };
  }
  global.ECGSttReviewLayout = Object.freeze({mount, context});
})(globalThis);
