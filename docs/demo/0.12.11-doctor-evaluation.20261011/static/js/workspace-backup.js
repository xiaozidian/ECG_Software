/* Local saved-work operations; never upload or automatically restore a DB. */
(() => {
  const panel = document.querySelector('#workspaceBackup');
  if (!panel) return;
  const button = panel.querySelector('#createWorkspaceBackup');
  const ack = panel.querySelector('#backupAcknowledged');
  const status = panel.querySelector('#backupStatus');
  const list = panel.querySelector('#backupList');
  let busy = false, enabled = false;
  const show = (text, error = false) => {
    status.textContent = text;
    status.classList.toggle('backup-error', error);
  };
  const controls = () => {
    button.disabled = busy || !enabled || !ack.checked;
    ack.disabled = busy || !enabled;
    panel.setAttribute('aria-busy', String(busy));
    list.querySelectorAll('button').forEach(item => { item.disabled = busy; });
    panel.querySelector('#refreshWorkspaceBackups').disabled = busy;
  };
  async function refresh(quiet = false) {
    const data = await api('/api/workspace/backups');
    enabled = data.enabled;
    panel.querySelector('#backupLocation').textContent = data.directory || data.reason;
    panel.querySelector('#restoredWorkspaceNotice').hidden = !data.recovered_workspace;
    list.replaceChildren();
    for (const item of data.items || []) {
      const row = document.createElement('li'), name = document.createElement('span');
      name.textContent = `${item.name} · ${(item.bytes / 1024 / 1024).toFixed(2)} MiB`;
      const verify = document.createElement('button');
      verify.type = 'button';verify.className = 'button secondary';verify.textContent = '校验';
      verify.setAttribute('aria-label', `校验备份 ${item.name}`);
      verify.onclick = () => run(async () => {
        show('正在校验备份摘要与数据库，请稍候…');
        const checked = await api(`/api/workspace/backups/${encodeURIComponent(item.name)}/verify`, {method: 'POST', body: '{}'});
        show(`校验通过：${item.name}。保存时间 ${new Date(checked.created_at).toLocaleString()}；不含原始心电文件。`);
      });
      row.append(name, verify);list.append(row);
    }
    if (!quiet) show(!enabled ? data.reason : data.items.length ? '列表为最近 10 份备份；需要时可重新校验。' : '尚无备份。先保存修改，再创建本机备份。');
    controls();
  }
  async function run(action) {
    if (busy) return;
    busy = true;controls();
    try { await action(); }
    catch (error) { show(error.message || '操作未完成，请检查本地服务后重试。', true); }
    finally { busy = false;controls(); }
  }
  ack.onchange = controls;
  button.onclick = () => run(async () => {
    if (!enabled || !ack.checked) return;
    if (state.reportDirty) throw Error('报告还有未保存修改。请先保存草稿，再创建备份。');
    show('正在保存并校验备份，请不要关闭本地服务…');
    const saved = await api('/api/workspace/backups', {method: 'POST', body: JSON.stringify({saved_work_acknowledged: true})});
    ack.checked = false;
    show(`备份已创建并校验：${saved.path}。${saved.warning || '原始心电文件、未保存修改及已导出 PDF 不在包内。'}`, !!saved.warning);
    try { await refresh(true); }
    catch (_) { show(`备份已创建并校验：${saved.path}。列表刷新失败，可点击“刷新列表”。`); }
  });
  panel.querySelector('#refreshWorkspaceBackups').onclick = () => run(() => refresh());
  const previous = loadSettings;
  loadSettings = async function () { await previous(); await run(() => refresh()); };
})();
