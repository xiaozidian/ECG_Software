"""The cheaper receipt path must stay equal to complete report indexing."""
from copy import deepcopy
import json
import pytest
from test_stt_comprehensive_records import comprehensive_api, review, checked
from ecg_core.stt_records import use_for
from test_analysis_provenance import synthetic_case


def equal_receipts(client,base):
    rows=checked(client.get(base+'/annotations'))['items']
    events=checked(client.get(base+'/report-events?category=ST&limit=1000'))['items']
    by_id={e['event_id']:e for e in events}
    report=checked(client.get(base+'/report'))['composition']
    compared=[]
    for row in rows:
        receipt=row.get('stt_review_receipt')
        if not receipt:continue
        event=by_id[receipt['event_id']]
        assert {k:v for k,v in receipt.items() if k!='report_use'}=={k:v for k,v in event['stt_review_receipt'].items() if k!='report_use'}
        assert receipt['report_use']==use_for(report,event)
        compared.append(receipt)
    return compared


@pytest.mark.parametrize('code',['st_depression','t_low_flat','no_change','artifact','indeterminate'])
def test_light_receipt_all_outcomes_equal_full_index(comprehensive_api,code):
    client,base=comprehensive_api
    payload=review(client,base,code)
    checked(client.post(base+'/annotations',json=payload))
    receipts=equal_receipts(client,base)
    assert len(receipts)==1 and receipts[0]['result_code']==code


def test_light_receipt_rechecks_changed_method_without_global_revision(comprehensive_api):
    client,base=comprehensive_api
    payload=review(client,base,'t_persistent_inversion')
    saved=checked(client.post(base+'/annotations',json=payload))
    old=equal_receipts(client,base)[0]
    assert old['review_state']=='reviewed'
    store=client.application.extensions['storage']
    revision=store.get_review(base.rsplit('/',1)[1])['revision']
    with store.connect() as db:
        row=db.execute('select details from annotations where id=?',(saved['id'],)).fetchone()
        details=json.loads(row[0]);details['measurement_protocol']['method_version']='engineering-old'
        db.execute('update annotations set details=? where id=?',(json.dumps(details),saved['id']))
    assert store.get_review(base.rsplit('/',1)[1])['revision']==revision
    fresh=equal_receipts(client,base)[0]
    assert fresh['review_state']!='reviewed'
    assert not any(fresh['report_eligibility'].values())
