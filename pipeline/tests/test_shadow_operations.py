import hashlib,hmac,json
from datetime import UTC,datetime
from fastapi.testclient import TestClient
from shadow_operations import ShadowInput,ShadowStore,create_app
def item():return ShadowInput(tenant_id="t",source_event_id="e",case_id="c",job_digest="j",candidate_set_digest="cs",input_schema_version="1",model_version="m",model_digest="md",policy_version="p",policy_digest="pd",advisory_output={},advisory_output_digest="o",latency_ms=1,trace_id="tr")
def test_shadow_lifecycle(tmp_path):
 s=ShadowStore(tmp_path/"s.db");r=s.submit(item(),"k");assert s.submit(item(),"k")["shadow_run_id"]==r["shadow_run_id"];r=s.outcome("t",r["shadow_run_id"],{"outcome":"advance"},1);r=s.compare("t",r["shadow_run_id"],{"match":True},2);assert r["status"]=="compared";assert s.replay("t",r["shadow_run_id"],"retry")["parent_id"]==r["shadow_run_id"]

def test_shadow_rejects_invalid_delete_and_exports_minimized(tmp_path):
 s=ShadowStore(tmp_path/"s.db");r=s.submit(item(),"k")
 try:s.delete("t",r["shadow_run_id"],1)
 except ValueError:pass
 else:raise AssertionError("delete must require expiry")
 expired=s.expire("t",r["shadow_run_id"],1);deleted=s.delete("t",r["shadow_run_id"],expired["version"])
 assert deleted["status"]=="deleted";assert s.export_minimized("t")==[];assert len(s.events("t",r["shadow_run_id"]))==3
 assert [receipt["action"] for receipt in s.receipts("t",r["shadow_run_id"])]==["expired","deleted"]

def signed_headers(key,method,path,body,scope,idempotency=None):
 timestamp=datetime.now(UTC).isoformat();request_id="request-1";trace_id="trace-1"
 canonical="\n".join((timestamp,method,path,"t","reviewer-a",scope,request_id,trace_id,hashlib.sha256(body).hexdigest()))
 headers={"X-Valence-Actor":"reviewer-a","X-Valence-Tenant":"t","X-Valence-Scopes":scope,"X-Request-Id":request_id,"X-Trace-Id":trace_id,"X-Valence-Internal-Timestamp":timestamp,"X-Valence-Internal-Signature":hmac.new(key.encode(),canonical.encode(),hashlib.sha256).hexdigest(),"Content-Type":"application/json"}
 if idempotency:headers["Idempotency-Key"]=idempotency
 return headers

def test_shadow_service_enforces_signed_tenant_scoped_lifecycle(tmp_path):
 key="s"*32;client=TestClient(create_app(ShadowStore(tmp_path/"shadow.db"),key));payload=item().model_dump(mode="json");body=json.dumps(payload,separators=(",",":")).encode();path="/v1/shadow-runs"
 assert client.post(path,content=body).status_code==422
 response=client.post(path,content=body,headers=signed_headers(key,"POST",path,body,"shadow:submit","shadow-1"));assert response.status_code==200;run=response.json();run_id=run["shadow_run_id"]
 outcome_path=f"/v1/shadow-runs/{run_id}/outcome";outcome=json.dumps({"version":1,"outcome":{"decision":"advance"}},separators=(",",":")).encode();response=client.post(outcome_path,content=outcome,headers=signed_headers(key,"POST",outcome_path,outcome,"shadow:outcome"));assert response.status_code==200
 report_path="/v1/shadow-runs/report";response=client.get(report_path,headers=signed_headers(key,"GET",report_path,b"","shadow:read"));assert response.status_code==200 and response.json()["total_cases"]==1
