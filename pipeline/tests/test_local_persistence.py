from datetime import UTC,datetime,timedelta
from local_persistence import LocalPersistence
from lifecycle_workers import run_review_lifecycle,run_shadow_lifecycle
from review_operations import ReviewStore,CreateReview
from shadow_operations import ShadowStore
def test_backup_restore_and_lifecycle(tmp_path):
 p=LocalPersistence(tmp_path/'db.sqlite');p.integrity();b=tmp_path/'b.sqlite';assert p.backup(b)>=0;assert p.restore(b)>=0
 r=ReviewStore(tmp_path/'r.sqlite');x=r.create(CreateReview(tenant_id='t',case_id='c',candidate_id='x',source_request_id='s',trace_id='tr',policy_version='p',model_version='m',model_digest='d',evidence_snapshot_digest='e',advisory_output_digest='a',risk='low'),'k');r.transition('t',x['review_id'],'u','claim',1);assert run_review_lifecycle(r,'t',datetime.now(UTC)+timedelta(minutes=16))['stale_claims_released']==1
