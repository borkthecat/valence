from shadow_operations import ShadowInput,ShadowStore
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
