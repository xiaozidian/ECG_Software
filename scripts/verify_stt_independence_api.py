"""Strict mathematical API checks against the *running packaged* native PE.

The parent driver constructs and adopts a real record with visible UI controls.
This additional gate deliberately uses version-controlled public APIs, including
the excluded rhythm status that has no editable public UI control. It never
seeds report approval or changes source beats. It is not a clinical validation.
"""
import copy
import json
from urllib.parse import urlencode
from uuid import uuid4

POLICY = 'independent_of_AF_AFL_reviews'
METHOD = 'stt-hospital-review-v2'
PROFILE = 'raw-200hz-fixed16s-st-perbeat-mean-v2'
ALGORITHM = 'stt-screening-0.3.2-independent-rhythm'
IDENTITY = ('case_id', 'analysis_basis', 'analysis_revision', 'beat_revision')


async def request(page, case_id, action, *, method='GET', payload=None):
    # Keep server number tokens (20.0 is not replaced by a JS Number 20) for
    # signatures and full historical JSON comparisons.
    text = await page.evaluate("""async p=>{if(typeof state==='undefined'||state.caseId!==p.id)throw Error('Actual workstation case is not ready');
      const headers={'Content-Type':'application/json','X-Actor':'demo-analyst',
       'X-CardioInsight-Request':'1','X-CardioInsight-Workspace':state.workspaceEpoch||''};
      const r=await fetch('/api/cases/'+p.id+'/'+p.action,
      {method:p.method,headers,
       ...(p.method==='GET'?{cache:'no-store'}:{body:JSON.stringify(p.payload)})});
      const text=await r.text();if(!r.ok)throw Error(p.action+': '+r.status+' '+text);return text;}""",
      dict(id=case_id, action=action, method=method, payload=payload))
    return json.loads(text)


def numeric_range(value):
    """Only a global request concurrency revision/attestation may advance."""
    return (
        {k: v for k, v in value.items() if k not in ('scope', 'server_identity', 'save_receipt', 'binding', 'result_digest')},
        {k: v for k, v in value['binding'].items() if k != 'scope_digest'},
        {k: v for k, v in value['server_identity'].items() if k != 'analysis_revision'},
    )


def rhythm_invalidated_composition(composition):
    """Existing non-ST acknowledgements still follow their actual lifecycle."""
    expected = copy.deepcopy(composition)
    reviews = expected.get('category_reviews', {})
    expected['category_reviews'] = {'ST': reviews['ST']} if 'ST' in reviews else {}
    for block in expected.get('diagnosis_blocks', []):
        if block.get('manual') and not str(block.get('key', '')).startswith('ST:'):
            block.update(needs_review=True, acknowledged=False)
    return expected


def projection(review, report, annotations, event, sections, event_id):
    """Full source/method measurements and saved ST/report state; no quiet merge."""
    row = next(a for a in annotations['items'] if 'annotation:' + str(a['id']) == event_id)
    assert row['stt_review_receipt']['review_state'] == 'reviewed'
    assert row['stt_review_receipt']['measurement_protocol']['method_version'] == METHOD
    assert row['stt_review_receipt']['measurement_protocol']['rhythm_policy'] == POLICY
    assert row['stt_review_receipt']['report_eligibility'] == dict(table=True, text=True, strip=True)
    assert event['stt_review_state'] == 'reviewed'
    assert event['stt_report_eligibility'] == dict(table=True, text=True, strip=True)
    assert event['basis_version'] == row['stt_review_receipt']['basis_version']
    proof = row['details']['stt_event_evidence']
    assert proof['rhythm_policy'] == POLICY and 'rhythm_exclusions_digest' not in proof
    assert proof['measurement_protocol']['method_version'] == METHOD
    assert review['analysis']['algorithm_version'] == ALGORITHM
    assert not review['analysis']['exclusions']['intervals']
    use = next(u for u in report['composition']['stt_report_use'] if u['event_id'] == event_id)
    assert use == dict(event_id=event_id, basis_version=event['basis_version'], table=True, text=True, strip=True)
    manual = next(b for b in report['composition']['diagnosis_blocks'] if b['key'] == 'ST:review:' + event_id)
    assert manual['manual'] is True and manual['acknowledged'] is True and manual['needs_review'] is False
    assert report['composition']['category_reviews']['ST'] == event['basis_version']
    return dict(analysis=review['analysis'], candidates=review['automatic_candidates']['items'],
                annotation=row, event={k: v for k, v in event.items() if k not in ('analysis_revision',)},
                composition=report['composition'], conclusion=report['conclusion'],
                report_sections={k: sections[k] for k in ('st_trends', 'st_events', 't_events', 'st_summary', 't_summary') if k in sections})


async def verify_stt_independence_api(page, case_id, receipt):
    """AF/AFL pending/edit/confirm/exclude/re-pend/delete preserve current ST."""
    event_id = receipt['event_id']
    report = await request(page, case_id, 'report')
    composition = copy.deepcopy(report['composition'])
    block = next(b for b in composition['diagnosis_blocks'] if b['key'] == 'ST:review:' + event_id)
    block.update(text='数学原生验收：保留医生独立 ST 意见。', manual=True, needs_review=False, acknowledged=True)
    composition.setdefault('category_reviews', {})['ST'] = receipt['basis_version']
    await request(page, case_id, 'report', method='PUT', payload=dict(expected_version=report['version'],
        status='draft', conclusion=report['conclusion'], composition=composition))

    async def snapshot():
        review = await request(page, case_id, 'stt-review')
        report = await request(page, case_id, 'report')
        annotations = await request(page, case_id, 'annotations')
        response = await request(page, case_id, 'report-events?' + urlencode(dict(category='ST', stt_group='all', ids=event_id, limit=2000)))
        event = next(e for e in response['items'] if e['event_id'] == event_id)
        sections = await request(page, case_id, 'report-sections')
        first, end = receipt['range']['start_s'], receipt['range']['end_s']
        assert end - first >= 60, 'Native independence gate needs a genuine full-minute ST event'
        measured = await request(page, case_id, 'stt-range', method='POST', payload=dict(
            scope={k: review[k] for k in IDENTITY}, start_sample=round(first * 200),
            end_sample=round(end * 200), leads=['II', 'V5'], measurement_ms=60))
        assert measured['method_profile']['id'] == PROFILE and measured['method_profile']['rhythm_policy'] == POLICY
        return projection(review, report, annotations, event, sections, event_id), numeric_range(measured), report

    baseline, base_range, initial_report = await snapshot()
    # ST acknowledgements are independent. AF acknowledgements must still be
    # invalidated by an AF change; assert this exact existing exception rather
    # than suppressing report-composition checks or guessing a ST-only fixture.
    baseline['composition'] = rhythm_invalidated_composition(baseline['composition'])
    initial_rhythm = await request(page, case_id, 'rhythm-review')
    original = copy.deepcopy(initial_rhythm['document'])
    comparisons = []
    previous_revision = initial_report['review_revision']
    for kind in ('AF', 'AFL'):
        identifier = str(uuid4())
        first, end = receipt['range']['start_s'], receipt['range']['end_s']
        # Every candidate overlaps the actual saved ST event, not an unrelated
        # quiet region. The edit moves a real bound while preserving overlap.
        episode = dict(id=identifier, start_s=first, end_s=end, kind=kind, status='pending', source='manual',
                       note='Native actual-PE ST independence: ' + kind)
        edited = {**episode, 'start_s': first + .5, 'end_s': end - .5}
        operations = [('pending-create', episode), ('bounds-edit', edited),
                      ('confirmed', {**edited, 'status': 'confirmed'}),
                      ('excluded', {**edited, 'status': 'excluded'}),
                      ('pending-again', edited), ('delete', None)]
        for label, current in operations:
            rhythm = await request(page, case_id, 'rhythm-review')
            document = copy.deepcopy(original)
            if current is not None: document['episodes'].append(current)
            response = await request(page, case_id, 'rhythm-review', method='PUT', payload={
                **{k: rhythm[k] for k in IDENTITY}, 'revision': rhythm['revision'], 'confirmed': True, 'document': document})
            assert response['document'] == document
            observed, observed_range, current_report = await snapshot()
            assert observed == baseline, (kind, label, 'ST measurements, record basis, uses, text acknowledgement or report changed')
            assert observed_range == base_range, (kind, label, 'Full-range per-beat statistics changed with AF/AFL')
            assert current_report['status'] == 'draft'
            assert current_report['review_revision'] == previous_revision + 1
            previous_revision = current_report['review_revision']
            comparisons.append(dict(kind=kind, operation=label, exact_ST_projection=True,
                full_range_statistics_exact=True, global_report_draft=True, review_revision=previous_revision))
    assert (await request(page, case_id, 'rhythm-review'))['document'] == original
    assert len(comparisons) == 12
    return dict(status='passed', gate='actual-packaged-PE-version-controlled-API',
        operations=comparisons, AF_AFL_cases=2, lifecycle_operations=12, source_and_beat_edits=0,
        ST_record_basis_preserved=True, ST_three_purposes_preserved=True,
        ST_manual_acknowledgement_preserved=True, ST_full_range_and_candidates_preserved=True,
        clinical_validation=False, patient_inputs_read=False, seeded_report_approval=False)
