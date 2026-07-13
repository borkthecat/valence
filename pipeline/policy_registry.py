"""Tenant-scoped, auditable policy version activation and rollback."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path


class PolicyRegistry:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS policies(tenant TEXT,version TEXT,digest TEXT,document TEXT,created TEXT,PRIMARY KEY(tenant,version))")
            db.execute("CREATE TABLE IF NOT EXISTS policy_state(tenant TEXT PRIMARY KEY,active_version TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS policy_events(id INTEGER PRIMARY KEY,tenant TEXT,actor TEXT,action TEXT,version TEXT,created TEXT)")

    def stage(self, tenant: str, version: str, document: dict, actor: str) -> dict:
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
        digest = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
        now = datetime.now(UTC).isoformat()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO policies VALUES(?,?,?,?,?)", (tenant, version, digest, canonical, now))
            db.execute("INSERT INTO policy_events(tenant,actor,action,version,created) VALUES(?,?,?,?,?)", (tenant, actor, "staged", version, now))
        return {"tenant_id": tenant, "version": version, "digest": digest, "active": False}

    def activate(self, tenant: str, version: str, actor: str, *, action: str = "activated") -> dict:
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute("SELECT digest FROM policies WHERE tenant=? AND version=?", (tenant, version)).fetchone()
            if row is None:
                raise KeyError(version)
            db.execute("INSERT INTO policy_state VALUES(?,?) ON CONFLICT(tenant) DO UPDATE SET active_version=excluded.active_version", (tenant, version))
            db.execute("INSERT INTO policy_events(tenant,actor,action,version,created) VALUES(?,?,?,?,?)", (tenant, actor, action, version, datetime.now(UTC).isoformat()))
        return {"tenant_id": tenant, "version": version, "digest": row[0], "active": True}

    def rollback(self, tenant: str, version: str, actor: str) -> dict:
        return self.activate(tenant, version, actor, action="rolled_back")

    def current(self, tenant: str) -> dict:
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT p.version,p.digest,p.document FROM policy_state s JOIN policies p ON p.tenant=s.tenant AND p.version=s.active_version WHERE s.tenant=?", (tenant,)).fetchone()
        if row is None:
            raise KeyError(tenant)
        return {"tenant_id": tenant, "version": row[0], "digest": row[1], "document": json.loads(row[2]), "active": True}

    def audit(self, tenant: str) -> list[dict]:
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute("SELECT actor,action,version,created FROM policy_events WHERE tenant=? ORDER BY id", (tenant,)).fetchall()
        return [dict(zip(("actor", "action", "version", "created_at"), row)) for row in rows]
