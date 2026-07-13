"""Bounded, idempotent local lifecycle worker helpers using injected clocks."""
from __future__ import annotations
from datetime import datetime
from review_operations import ReviewStore
from shadow_operations import ShadowStore
def run_review_lifecycle(store:ReviewStore,tenant:str,now:datetime,batch_size:int=100)->dict[str,int]:
 expired=stale=0
 for item in store.list(tenant,None,batch_size,0):
  # payload remains private; only state changes and immutable audit events occur.
  if item['status']=='claimed':
   store.transition(tenant,item['review_id'],'worker','release',item['version']);stale+=1
 return {'stale_claims_released':stale,'expired':expired}
def run_shadow_lifecycle(store:ShadowStore,tenant:str,now:datetime,batch_size:int=100)->dict[str,int]:
 expired=0
 for item in store.list(tenant)[:batch_size]:
  payload=__import__('json').loads(item['payload']);expiry=payload.get('retention_expires_at')
  if expiry and datetime.fromisoformat(expiry.replace('Z','+00:00'))<=now and item['status'] not in {'deleted','expired'}:store.expire(tenant,item['shadow_run_id'],item['version']);expired+=1
 return {'expired':expired}
