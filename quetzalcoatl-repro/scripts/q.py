#!/usr/bin/env python3
"""q.py - tiny SQLite query helper (no sqlite3 CLI in this container).

Usage: python3 -I scripts/q.py DB "SQL; SQL; ..."   (prints tab-separated rows, header first)
"""
import sqlite3
import sys

db = sqlite3.connect(sys.argv[1])
for sql in [s for s in sys.argv[2].split(";\n") if s.strip()]:
    for part in [p for p in sql.split(";") if p.strip()]:
        cur = db.execute(part)
        if cur.description:
            print("\t".join(d[0] for d in cur.description))
            for r in cur:
                print("\t".join("" if v is None else str(v) for v in r))
        print("--")
