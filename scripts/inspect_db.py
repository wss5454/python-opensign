"""Inspect SQLite schema."""
import sqlite3

c = sqlite3.connect("wallacesign.db")
print("tables:", c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
for t in ["documents", "signers", "signer_widgets", "users", "audit_events"]:
    try:
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})").fetchall()]
        print(t, cols)
    except Exception as e:
        print(t, e)
