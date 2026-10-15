"""Independent SQLite/WAL storage for CareLoop source records and derived search entries."""
from __future__ import annotations
import json, sqlite3, threading, time
from pathlib import Path
from typing import Any

Item = dict[str, Any]
def patient_pk(patient_id: str) -> str: return f"PATIENT#{patient_id}"

def _no_floats(value: Any) -> None:
    if isinstance(value, float): raise TypeError("CareLoop stores scaled integer values, not floats")
    if isinstance(value, dict):
        for part in value.values(): _no_floats(part)
    elif isinstance(value, list):
        for part in value: _no_floats(part)

class CareLoopStorage:
    def __init__(self, path: str | Path = "data/careloop.db", clock=time.time) -> None:
        if str(path) != ":memory:": Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path, self.clock = str(path), clock
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock, self._db:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("CREATE TABLE IF NOT EXISTS items (patient_id TEXT NOT NULL, record_id TEXT NOT NULL, kind TEXT NOT NULL, item TEXT NOT NULL, expires_at INTEGER, deleted_at INTEGER, PRIMARY KEY(patient_id, record_id))")
            self._db.execute("CREATE TABLE IF NOT EXISTS search_entries (patient_id TEXT NOT NULL, source_id TEXT NOT NULL, entry_id TEXT NOT NULL, text TEXT NOT NULL, created_at INTEGER NOT NULL, PRIMARY KEY(patient_id, entry_id), FOREIGN KEY(patient_id, source_id) REFERENCES items(patient_id, record_id) ON DELETE CASCADE)")
            # A request key is a durable mapping, rather than an in-memory
            # retry cache: clients may safely retry after a process restart.
            self._db.execute("CREATE TABLE IF NOT EXISTS idempotency_keys (patient_id TEXT NOT NULL, operation TEXT NOT NULL, request_key TEXT NOT NULL, record_id TEXT NOT NULL, fingerprint TEXT NOT NULL, PRIMARY KEY(patient_id, operation, request_key))")
            self._db.execute("CREATE INDEX IF NOT EXISTS search_scope ON search_entries(patient_id, source_id)")
    def put(self, patient_id: str, record_id: str, kind: str, item: Item, *, expires_at: int | None = None) -> Item:
        _no_floats(item); stored = dict(item) | {"id":record_id,"patient_id":patient_id,"type":kind}
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO items(patient_id,record_id,kind,item,expires_at,deleted_at) VALUES(?,?,?,?,?,NULL)", (patient_id,record_id,kind,json.dumps(stored,allow_nan=False),expires_at))
        return stored
    def get(self, patient_id: str, record_id: str, *, include_deleted=False) -> Item | None:
        with self._lock: row=self._db.execute("SELECT item,expires_at,deleted_at FROM items WHERE patient_id=? AND record_id=?",(patient_id,record_id)).fetchone()
        if not row or (row[2] is not None and not include_deleted) or (row[1] is not None and row[1] <= self.clock()): return None
        return json.loads(row[0])
    def list(self, patient_id: str, kind: str | None = None, *, include_deleted=False) -> list[Item]:
        sql="SELECT item,expires_at,deleted_at FROM items WHERE patient_id=?"; args=[patient_id]
        if kind: sql+=" AND kind=?"; args.append(kind)
        sql+=" ORDER BY json_extract(item, '$.created_at'), record_id"
        with self._lock: rows=self._db.execute(sql,args).fetchall()
        now=self.clock(); return [json.loads(r[0]) for r in rows if (include_deleted or r[2] is None) and (r[1] is None or r[1]>now)]
    def index(self, patient_id: str, source_id: str, entry_id: str, text: str, created_at: int) -> None:
        if not self.get(patient_id, source_id): raise KeyError("source record is not active")
        with self._lock, self._db: self._db.execute("INSERT OR REPLACE INTO search_entries VALUES(?,?,?,?,?)",(patient_id,source_id,entry_id,text.lower(),created_at))
    def search(self, patient_id: str, query: str) -> list[Item]:
        terms=[x.lower() for x in query.split() if x]
        if not terms: return []
        with self._lock: rows=self._db.execute("SELECT source_id,text FROM search_entries WHERE patient_id=?",(patient_id,)).fetchall()
        found=[]
        for source_id,text in rows:
            if all(term in text for term in terms):
                item=self.get(patient_id,source_id)
                if item: found.append(item)
        return found
    def idempotency_get(self, patient_id: str, operation: str, request_key: str) -> tuple[str, str] | None:
        with self._lock:
            return self._db.execute("SELECT record_id,fingerprint FROM idempotency_keys WHERE patient_id=? AND operation=? AND request_key=?", (patient_id, operation, request_key)).fetchone()
    def idempotency_put(self, patient_id: str, operation: str, request_key: str, record_id: str, fingerprint: str) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO idempotency_keys(patient_id,operation,request_key,record_id,fingerprint) VALUES(?,?,?,?,?)", (patient_id, operation, request_key, record_id, fingerprint))
    def patient_ids(self) -> list[str]:
        with self._lock:
            return [row[0] for row in self._db.execute("SELECT DISTINCT patient_id FROM items").fetchall()]
    def soft_delete(self, patient_id: str, record_id: str, deleted_at: int | None = None) -> bool:
        with self._lock, self._db:
            result=self._db.execute("UPDATE items SET deleted_at=? WHERE patient_id=? AND record_id=? AND deleted_at IS NULL",(int(self.clock()) if deleted_at is None else deleted_at,patient_id,record_id))
            self._db.execute("DELETE FROM search_entries WHERE patient_id=? AND source_id=?",(patient_id,record_id))
        return result.rowcount > 0
    def purge(self, now: int | None = None, *, patient_id: str | None = None) -> int:
        now=int(self.clock()) if now is None else now
        scope_sql = " AND patient_id=?" if patient_id is not None else ""
        scope_args = (patient_id,) if patient_id is not None else ()
        with self._lock, self._db:
            result=self._db.execute("DELETE FROM items WHERE (deleted_at IS NOT NULL OR (expires_at IS NOT NULL AND expires_at <= ?))" + scope_sql,(now, *scope_args))
            self._db.execute("DELETE FROM search_entries WHERE (patient_id,source_id) NOT IN (SELECT patient_id,record_id FROM items WHERE deleted_at IS NULL AND (expires_at IS NULL OR expires_at > ?))" + (" AND patient_id=?" if patient_id is not None else ""),(now, *scope_args))
        return result.rowcount
    def close(self) -> None: self._db.close()
