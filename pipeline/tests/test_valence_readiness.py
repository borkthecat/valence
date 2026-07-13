import json
from valence_readiness import report
def test_readiness_never_promotes_missing_evidence():
 rows=report();assert all(row.status in {"passed","failed","unmeasured","externally blocked","intentionally deferred","not applicable"} for row in rows);assert any(row.status=="unmeasured" for row in rows);assert any(row.status=="failed" for row in rows)
