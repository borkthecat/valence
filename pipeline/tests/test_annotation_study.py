from annotation_study import StudyStore
def test_blind_annotation_and_adjudication(tmp_path):
 s=StudyStore(tmp_path/'a.db');s.add_case('t','c',{'job':{},'candidates':[{'candidate_id':'x'}]},['r1','r2']);assert s.queue('t','r1')==['c'];assert 'annotations' not in s.case('t','c','r1');s.save('t','c','r1',{'hard_eligibility':'pass','graded_relevance':3},True);s.save('t','c','r2',{'hard_eligibility':'fail','graded_relevance':1},True);assert s.disagreements('t','c');s.adjudicate('t','c','adj',{'hard_eligibility':'unknown'},'conflict');s.freeze('t','c')
