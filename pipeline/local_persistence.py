"""Local/research SQLite lifecycle primitives; not an enterprise database layer."""
from __future__ import annotations
import shutil,sqlite3,time
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION=1
@dataclass(frozen=True)
class RecoveryMeasurement: backup_seconds:float; restore_seconds:float; rpo_seconds:int=0; rto_seconds:int=0
class LocalPersistence:
 def __init__(self,path:str|Path):self.path=Path(path);self.connect().close()
 def connect(self):
  c=sqlite3.connect(self.path);c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA journal_mode=WAL');c.execute('CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL)');row=c.execute('SELECT version FROM schema_version').fetchone()
  if row is None:c.execute('INSERT INTO schema_version VALUES(?)',(SCHEMA_VERSION,))
  elif row[0]>SCHEMA_VERSION:raise RuntimeError('database schema is newer than this application')
  c.commit();return c
 def integrity(self):
  with self.connect() as c:
   if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('sqlite integrity check failed')
 def backup(self,target:str|Path):
  start=time.perf_counter();target=Path(target)
  with self.connect() as source,sqlite3.connect(target) as dest:source.backup(dest)
  self.__class__(target).integrity();return time.perf_counter()-start
 def restore(self,backup:str|Path):
  start=time.perf_counter();shutil.copy2(backup,self.path);self.integrity();return time.perf_counter()-start
