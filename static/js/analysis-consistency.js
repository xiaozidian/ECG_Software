"use strict";
// Optimistic, version-bound reads. This does not claim a filesystem snapshot.
const ECGAnalysisConsistency = (() => {
  const keys = ['analysis_basis', 'analysis_revision'];
  function identity(value) {
    const source = value?.clinical_identity || value;
    if (!source || keys.some(key => source[key] === undefined || source[key] === null))
      throw Error('分析依据缺失，请重新载入病例');
    return Object.fromEntries(keys.map(key => [key, source[key]]));
  }
  function assertSame(expected, actual) {
    const a = identity(expected), b = identity(actual);
    if (keys.some(key => String(a[key]) !== String(b[key])))
      throw Error('分析期间病例依据已变化，请重新读取后复核');
    return b;
  }
  function assertReportWave(wave, state) {
    const header = identity(state.caseData), report = state.report;
    if (state.currentPage !== 'report' || !Number.isInteger(report?.review_revision))
      return assertSame(wave, header);
    if (report.case_id && report.case_id !== state.caseId) throw Error('报告来自其他病例，请重新读取');
    // PUT acknowledges the current review revision but omits the GET-only basis digest.
    // Both snapshots must describe the same source. The newest revision owns the wave.
    const digest = report.current_analysis_basis?.digest || header.analysis_basis;
    if (digest !== header.analysis_basis) throw Error('病例来源已变化，请重新读取后复核');
    return assertSame(wave, {analysis_basis: digest, analysis_revision: Math.max(header.analysis_revision, report.review_revision)});
  }
  function url(id, kind = '', params = {}, basis = {}) {
    return `/api/cases/${encodeURIComponent(id)}${kind ? '/' + kind : ''}?${new URLSearchParams({...params, ...basis})}`;
  }
  async function read(api, id, readers, anchor = null) {
    const basis = identity(anchor || await api(url(id, 'analysis-basis')));
    const results = await Promise.all(readers.map(reader => reader(basis)));
    results.filter(result => result !== null).forEach(result => assertSame(basis, result));
    // Catch edits after an early request completed but before the slowest did.
    assertSame(basis, await api(url(id, 'analysis-basis', {}, basis)));
    return results;
  }
  return {identity, assertSame, assertReportWave, url, read};
})();
if (typeof module !== 'undefined') module.exports = ECGAnalysisConsistency;
