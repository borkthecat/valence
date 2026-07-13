import json
from valence_readiness import report
def test_readiness_never_promotes_missing_evidence():
 rows=report();assert all(row.status in {"passed","failed","unmeasured","externally blocked","intentionally deferred","not applicable"} for row in rows);assert not any(row.status=="failed" for row in rows);assert any(row.status=="externally blocked" for row in rows);assert all(row.blocker_type!="repository work" for row in rows)
