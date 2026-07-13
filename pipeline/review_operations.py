"""Durable, tenant-scoped human-review queue for shadow deployments.

This service expects an authenticated upstream to inject the actor headers; it
never accepts anonymous requests or cross-tenant operations.
"""
from __future__ import annotations

import json, os, sqlite3, uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from internal_service_auth import InternalActor, actor_dependency, require_scope

Status = Literal["pending", "claimed", "in_review", "escalated", "resolved", "reopened", "expired", "cancelled"]

class Model(BaseModel): model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())
class CreateReview(Model):
    tenant_id: str; case_id: str; candidate_id: str; source_request_id: str; trace_id: str = Field(min_length=1,max_length=128); policy_version: str; model_version: str
    model_digest: str; evidence_snapshot_digest: str; advisory_output_digest: str; reason_codes: tuple[str,...] = (); risk: str; uncertainty: float = Field(default=0,ge=0,le=1); due_at: datetime | None=None; priority: int = Field(default=0,ge=0,le=100)
class Decision(Model): resolution: str = Field(min_length=1,max_length=4096); version: int = Field(ge=1)
class Action(Model): version: int = Field(ge=1)

class ReviewStore:
    def __init__(self, path: str | Path):
        self.path=str(path); self.migrate()
    @contextmanager
    def db(self):
        con=sqlite3.connect(self.path); con.row_factory=sqlite3.Row
        try: yield con; con.commit()
        except: con.rollback(); raise
        finally: con.close()
    def migrate(self):
        with self.db() as c:
            c.execute("CREATE TABLE IF NOT EXISTS reviews (id TEXT PRIMARY KEY, tenant TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, claimed_by TEXT, resolution TEXT, version INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, idempotency TEXT NOT NULL, UNIQUE(tenant,idempotency))")
            c.execute("CREATE INDEX IF NOT EXISTS reviews_tenant_status ON reviews(tenant,status,created_at)")
            c.execute("CREATE TABLE IF NOT EXISTS review_events (id INTEGER PRIMARY KEY AUTOINCREMENT, review_id TEXT NOT NULL, tenant TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS review_receipts (id TEXT PRIMARY KEY, review_id TEXT NOT NULL, tenant TEXT NOT NULL, action TEXT NOT NULL, version INTEGER NOT NULL, created_at TEXT NOT NULL)")
    def create(self, item: CreateReview, key: str) -> dict:
        now=datetime.now(UTC).isoformat(); review_id=str(uuid.uuid4())
        with self.db() as c:
            row=c.execute("SELECT * FROM reviews WHERE tenant=? AND idempotency=?",(item.tenant_id,key)).fetchone()
            if row:return self._row(row)
            c.execute("INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?)",(review_id,item.tenant_id,item.model_dump_json(),"pending",None,None,1,now,now,key)); self._event(c,review_id,item.tenant_id,"system","created",{})
            return self._row(c.execute("SELECT * FROM reviews WHERE id=?",(review_id,)).fetchone())
    def create_many(self, items: tuple[tuple[CreateReview, str], ...]) -> list[dict]:
        """Atomically create a review-required batch, preserving retry identities."""
        now=datetime.now(UTC).isoformat(); created: list[dict]=[]
        with self.db() as c:
            for item, key in items:
                row=c.execute("SELECT * FROM reviews WHERE tenant=? AND idempotency=?",(item.tenant_id,key)).fetchone()
                if row:
                    created.append(self._row(row)); continue
                review_id=str(uuid.uuid4())
                c.execute("INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?)",(review_id,item.tenant_id,item.model_dump_json(),"pending",None,None,1,now,now,key))
                self._event(c,review_id,item.tenant_id,"system","created",{})
                created.append(self._row(c.execute("SELECT * FROM reviews WHERE id=?",(review_id,)).fetchone()))
        return created
    def get(self, tenant:str, review_id:str)->dict:
        with self.db() as c:
            row=c.execute("SELECT * FROM reviews WHERE id=? AND tenant=?",(review_id,tenant)).fetchone()
            if not row: raise KeyError(review_id)
            return self._row(row)
    def transition(self, tenant:str, review_id:str, actor:str, action:str, version:int, resolution:str|None=None)->dict:
        allowed={"claim":({"pending","reopened"},"claimed"),"release":({"claimed","in_review"},"pending"),"decision":({"claimed","in_review","escalated"},"resolved"),"escalate":({"claimed","in_review"},"escalated"),"reopen":({"resolved"},"reopened"),"expire":({"pending","claimed","in_review","escalated","reopened"},"expired"),"cancel":({"pending","claimed","in_review","escalated","reopened"},"cancelled")}
        with self.db() as c:
            row=c.execute("SELECT * FROM reviews WHERE id=? AND tenant=?",(review_id,tenant)).fetchone()
            if not row: raise KeyError(review_id)
            if row["version"]!=version: raise ValueError("version conflict")
            if row["status"] not in allowed[action][0]: raise ValueError("invalid state transition")
            status=allowed[action][1]; claimed=actor if action=="claim" else None if action=="release" else row["claimed_by"]
            now=datetime.now(UTC).isoformat(); c.execute("UPDATE reviews SET status=?,claimed_by=?,resolution=?,version=?,updated_at=? WHERE id=?",(status,claimed,resolution or row["resolution"],version+1,now,review_id)); self._event(c,review_id,tenant,actor,action,{"resolution":resolution} if resolution else {})
            if action in {"expire","cancel"}:c.execute("INSERT INTO review_receipts VALUES(?,?,?,?,?,?)",(str(uuid.uuid4()),review_id,tenant,action,version+1,now))
            return self._row(c.execute("SELECT * FROM reviews WHERE id=?",(review_id,)).fetchone())
    def list(self,tenant:str,status:str|None,limit:int,offset:int)->list[dict]:
        with self.db() as c:
            rows=c.execute("SELECT * FROM reviews WHERE tenant=? AND (? IS NULL OR status=?) ORDER BY created_at DESC LIMIT ? OFFSET ?",(tenant,status,status,limit,offset)).fetchall(); return [self._row(r,False) for r in rows]
    def audit(self,tenant:str,review_id:str)->list[dict]:
        with self.db() as c:return [dict(r) for r in c.execute("SELECT actor,action,detail,created_at FROM review_events WHERE tenant=? AND review_id=? ORDER BY id",(tenant,review_id))]
    def receipts(self,tenant:str,review_id:str)->list[dict]:
        with self.db() as c:return [dict(r) for r in c.execute("SELECT id,action,version,created_at FROM review_receipts WHERE tenant=? AND review_id=? ORDER BY created_at",(tenant,review_id))]
    def _event(self,c,r,t,a,action,detail): c.execute("INSERT INTO review_events(review_id,tenant,actor,action,detail,created_at) VALUES (?,?,?,?,?,?)",(r,t,a,action,json.dumps(detail,sort_keys=True),datetime.now(UTC).isoformat()))
    def _row(self,row,detail=True):
        item=json.loads(row["payload"]); return {"review_id":row["id"],"tenant_id":row["tenant"],"case_id":item["case_id"],"candidate_id":item["candidate_id"],"status":row["status"],"claimed_by":row["claimed_by"],"resolution":row["resolution"],"version":row["version"],"created_at":row["created_at"],"updated_at":row["updated_at"],"due_at":item.get("due_at"),**({"reason_codes":item["reason_codes"],"risk":item["risk"],"uncertainty":item["uncertainty"]} if detail else {})}

def create_router(store: ReviewStore, internal_key: str | None = None)->APIRouter:
    key = internal_key if internal_key is not None else os.environ.get("VALENCE_REVIEW_INTERNAL_KEY")
    if key is None or len(key) < 32:
        raise RuntimeError("VALENCE_REVIEW_INTERNAL_KEY must be configured with at least 32 characters")
    actor = actor_dependency(key)
    router = APIRouter()
    @router.post("/v1/reviews")
    def create(item:CreateReview,a:InternalActor=Depends(actor),key:str=Header(...,alias="Idempotency-Key")):
        require_scope(a,"review:claim","review:admin")
        if item.tenant_id!=a.tenant_id: raise HTTPException(403,"tenant mismatch")
        return store.create(item,key)
    @router.get("/v1/reviews")
    def list_reviews(status:str|None=None,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),a:InternalActor=Depends(actor)):
        require_scope(a,"review:read","review:admin"); return store.list(a.tenant_id,status,limit,offset)
    @router.get("/v1/reviews/{review_id}")
    def get(review_id:str,a:InternalActor=Depends(actor)):
        require_scope(a,"review:read","review:admin")
        try:return store.get(a.tenant_id,review_id)
        except KeyError:raise HTTPException(404,"review not found")
    def trans(review_id:str,body:Action|Decision,a:InternalActor,action:str,scope:str):
        require_scope(a,scope,"review:admin")
        try:return store.transition(a.tenant_id,review_id,a.actor_id,action,body.version,getattr(body,"resolution",None))
        except KeyError:raise HTTPException(404,"review not found")
        except ValueError as e:raise HTTPException(409,str(e))
    @router.post("/v1/reviews/{review_id}/claim")
    def claim(review_id:str,body:Action,a:InternalActor=Depends(actor)):return trans(review_id,body,a,"claim","review:claim")
    @router.post("/v1/reviews/{review_id}/release")
    def release(review_id:str,body:Action,a:InternalActor=Depends(actor)):return trans(review_id,body,a,"release","review:claim")
    @router.post("/v1/reviews/{review_id}/decision")
    def decide(review_id:str,body:Decision,a:InternalActor=Depends(actor)):return trans(review_id,body,a,"decision","review:decide")
    @router.post("/v1/reviews/{review_id}/escalate")
    def escalate(review_id:str,body:Action,a:InternalActor=Depends(actor)):return trans(review_id,body,a,"escalate","review:escalate")
    @router.post("/v1/reviews/{review_id}/reopen")
    def reopen(review_id:str,body:Action,a:InternalActor=Depends(actor)):return trans(review_id,body,a,"reopen","review:override")
    @router.post("/v1/reviews/{review_id}/expire")
    def expire(review_id:str,body:Action,a:InternalActor=Depends(actor)):return trans(review_id,body,a,"expire","review:retention")
    @router.post("/v1/reviews/{review_id}/cancel")
    def cancel(review_id:str,body:Action,a:InternalActor=Depends(actor)):return trans(review_id,body,a,"cancel","review:retention")
    @router.get("/v1/reviews/{review_id}/audit")
    def audit(review_id:str,a:InternalActor=Depends(actor)):
        require_scope(a,"review:audit","review:admin"); return {"events":store.audit(a.tenant_id,review_id),"receipts":store.receipts(a.tenant_id,review_id)}
    return router


def create_app(store: ReviewStore, internal_key: str | None = None)->FastAPI:
    app=FastAPI(title="Valence Review Operations",version="1.0")
    app.include_router(create_router(store, internal_key))
    return app
