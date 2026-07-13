import json
from annotation_study import StudyStore

def record(case_id):return {"case_id":case_id,"job":{"id":"job"},"candidates":[{"candidate_id":"x"}]}
def label(value="pass",relevance=2):return {"hard_eligibility":value,"human_review_required":False,"evidence_sufficiency":"sufficient","fraud_or_inconsistency_risk":"none","graded_relevance":relevance,"confidence":.8}
def test_full_annotation_lifecycle_and_export(tmp_path):
 s=StudyStore(tmp_path/'a.db');ids=s.create_calibration_batch('t',[record('c1'),record('c2')],['r1','r2','r3'],conflicts=['r1']);assert len(ids)==2
 assert s.queue('t','r1')==[];assert s.queue('t','r2') and s.queue('t','r3') # balancing excludes conflicted reviewer
 c=ids[0];assert 'independent_labels' not in s.case('t',c,'r2');s.save('t',c,'r2',label(),True);s.save('t',c,'r3',label(),True);assert s.disagreements('t',c)=={};s.freeze('t',c)
 try:s.save('t',c,'r2',label('fail'),False)
 except ValueError:pass
 else:raise AssertionError('post-freeze edit accepted')
 out=tmp_path/'export';manifest=s.export('t',out);assert manifest['records']==1
 for name in ('canonical.jsonl','dataset_manifest.json','benchmark_manifest.json','agreement_report.json','audit_report.json','exclusion_report.json'):assert (out/name).exists()
 exported=json.loads((out/'agreement_report.json').read_text());assert exported['agreed']==1 and exported['adjudicated']==0
def test_material_disagreement_adjudication_and_versioned_correction(tmp_path):
 s=StudyStore(tmp_path/'a.db');s.add_case('t','c',record('c'),['r1','r2']);s.save('t','c','r1',label('pass',3),True);s.save('t','c','r2',label('fail',1),True);assert 'hard_eligibility' in s.disagreements('t','c');s.assign_adjudicator('t','c','adj');s.adjudicate('t','c','adj',label('unknown',2),'independent conflict');s.freeze('t','c');new=s.correct('t','c',record('c'),['r1','r2']);assert new=='c-v2'
def test_agreed_requires_identical_independent_labels(tmp_path):
 s=StudyStore(tmp_path/'a.db');s.add_case('t','c',record('c'),['r1','r2']);s.save('t','c','r1',label(relevance=2),True);s.save('t','c','r2',label(relevance=3),True)
 try:s.freeze('t','c')
 except ValueError:pass
 else:raise AssertionError('non-identical labels were incorrectly agreed')
