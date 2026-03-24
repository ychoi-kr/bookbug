"""bookbug_db — 출판 원고 교정용 이슈 트래커 DB 레이어

CLI(bookbug.py)와 MCP 서버(bookbug_mcp.py)가 공유하는 DB 접근 모듈.
DB 위치: ~/.bookbug/bookbug.db
"""

import contextlib
import csv
import json
import sqlite3
from pathlib import Path

DB_DIR = Path.home() / ".bookbug"
DB_PATH = DB_DIR / "bookbug.db"

VALID_STATUSES = ("open", "in_progress", "resolved", "wontfix", "deferred")
VALID_SEVERITIES = ("critical", "major", "normal", "minor", "trivial")

# ─── Schema ───────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT UNIQUE NOT NULL,
    title       TEXT NOT NULL,
    description TEXT DEFAULT '',
    base_path   TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    deleted_at  TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS issues (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    issue_key   TEXT NOT NULL,
    title       TEXT NOT NULL,
    description TEXT DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'open'
                CHECK(status IN ('open','in_progress','resolved','wontfix','deferred')),
    category    TEXT DEFAULT '',
    severity    TEXT NOT NULL DEFAULT 'normal'
                CHECK(severity IN ('critical','major','normal','minor','trivial')),
    location    TEXT DEFAULT '',
    chapter     TEXT DEFAULT '',
    assignee    TEXT DEFAULT '',
    reporter    TEXT NOT NULL DEFAULT 'claude',
    suggestion  TEXT DEFAULT '',
    resolution  TEXT DEFAULT '',
    source      TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    resolved_at TEXT,
    deleted_at  TEXT DEFAULT NULL,
    UNIQUE(project_id, issue_key)
);

CREATE TABLE IF NOT EXISTS issue_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id    INTEGER NOT NULL REFERENCES issues(id),
    field       TEXT NOT NULL,
    old_value   TEXT,
    new_value   TEXT,
    changed_by  TEXT DEFAULT '',
    changed_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    note        TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id    INTEGER NOT NULL REFERENCES issues(id),
    tag         TEXT NOT NULL,
    UNIQUE(issue_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_issues_project  ON issues(project_id);
CREATE INDEX IF NOT EXISTS idx_issues_status   ON issues(status);
CREATE INDEX IF NOT EXISTS idx_issues_chapter  ON issues(chapter);
CREATE INDEX IF NOT EXISTS idx_issues_category ON issues(category);
CREATE INDEX IF NOT EXISTS idx_history_issue   ON issue_history(issue_id);
CREATE INDEX IF NOT EXISTS idx_tags_issue      ON tags(issue_id);
CREATE INDEX IF NOT EXISTS idx_tags_tag        ON tags(tag);
"""

# ─── DB 연결 (Context Manager) ────────────────────────────────────────────────

@contextlib.contextmanager
def get_db():
    """DB 연결을 열고 with 블록 종료 시 반드시 닫는다.

    DB_PATH를 호출 시점에 참조하므로 테스트에서 monkey-patch가 정상 작동한다.

    Usage:
        with get_db() as conn:
            conn.execute(...)
    """
    path = DB_PATH  # 호출 시점의 전역 변수를 참조
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    # 소프트 딜리트 컬럼 마이그레이션 (구 DB 호환)
    for table, col in (("projects", "deleted_at"), ("issues", "deleted_at")):
        existing = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT DEFAULT NULL")
            conn.commit()

    try:
        yield conn
    finally:
        conn.close()

# ─── 헬퍼 ─────────────────────────────────────────────────────────────────────

def next_issue_key(conn: sqlite3.Connection, project_id: int) -> str:
    """프로젝트 내 다음 issue_key(정수 문자열) 반환. 예: '1', '2', '3'"""
    row = conn.execute(
        "SELECT MAX(CAST(issue_key AS INTEGER)) FROM issues WHERE project_id=?",
        (project_id,)
    ).fetchone()
    num = (row[0] or 0) + 1
    return str(num)

def record_change(conn: sqlite3.Connection, issue_id: int, field: str,
                  old_val, new_val, changed_by: str = "", note: str = ""):
    if str(old_val) != str(new_val):
        conn.execute(
            "INSERT INTO issue_history(issue_id, field, old_value, new_value, changed_by, note) "
            "VALUES(?,?,?,?,?,?)",
            (issue_id, field, str(old_val), str(new_val), changed_by, note)
        )

def row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)

# ─── 프로젝트 CRUD ────────────────────────────────────────────────────────────

def db_project_create(conn: sqlite3.Connection, slug: str, title: str,
                      description: str = "", base_path: str = "") -> dict:
    try:
        conn.execute(
            "INSERT INTO projects(slug, title, description, base_path) VALUES(?,?,?,?)",
            (slug, title, description, base_path)
        )
        conn.commit()
        return {"ok": True, "slug": slug, "title": title}
    except sqlite3.IntegrityError:
        return {"ok": False, "error": f"슬러그 '{slug}'는 이미 존재합니다"}

def db_project_list(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        "SELECT p.*, COUNT(i.id) as issue_count FROM projects p "
        "LEFT JOIN issues i ON p.id=i.project_id AND i.deleted_at IS NULL "
        "WHERE p.deleted_at IS NULL GROUP BY p.id ORDER BY p.updated_at DESC"
    ).fetchall()
    result = []
    for r in rows:
        open_count = conn.execute(
            "SELECT COUNT(*) FROM issues WHERE project_id=? AND deleted_at IS NULL "
            "AND status NOT IN ('resolved','wontfix')",
            (r["id"],)
        ).fetchone()[0]
        result.append({
            "slug": r["slug"],
            "title": r["title"],
            "description": r["description"],
            "base_path": r["base_path"],
            "created_at": r["created_at"],
            "issue_count": r["issue_count"],
            "open_count": open_count,
        })
    return result

def db_project_get(conn: sqlite3.Connection, slug: str):
    return conn.execute(
        "SELECT * FROM projects WHERE slug=? AND deleted_at IS NULL", (slug,)
    ).fetchone()

def db_project_show(conn: sqlite3.Connection, slug: str):
    p = db_project_get(conn, slug)
    if not p:
        return None
    stats_rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM issues WHERE project_id=? AND deleted_at IS NULL GROUP BY status",
        (p["id"],)
    ).fetchall()
    return {
        "slug": p["slug"],
        "title": p["title"],
        "description": p["description"],
        "base_path": p["base_path"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "status_summary": {r["status"]: r["cnt"] for r in stats_rows},
    }

# ─── 이슈 CRUD ────────────────────────────────────────────────────────────────

def db_issue_add(conn: sqlite3.Connection, project_id: int,
                 title: str, description: str = "", category: str = "",
                 severity: str = "normal", location: str = "", chapter: str = "",
                 assignee: str = "", reporter: str = "claude",
                 suggestion: str = "", source: str = "manual") -> dict:
    key = next_issue_key(conn, project_id)
    try:
        conn.execute(
            """INSERT INTO issues(project_id, issue_key, title, description, status, category,
               severity, location, chapter, assignee, reporter, suggestion, source)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (project_id, key, title, description, "open", category,
             severity, location, chapter, assignee, reporter, suggestion, source)
        )
        conn.commit()
        return {"ok": True, "issue_key": key, "title": title}
    except sqlite3.IntegrityError as e:
        return {"ok": False, "error": str(e)}

def db_issue_get(conn: sqlite3.Connection, key_or_id: str, project_slug: str = ""):
    """issue_key(정수 문자열) 또는 내부 id로 이슈 조회.
    project_slug를 주면 해당 프로젝트 범위에서만 조회하며,
    크로스 프로젝트 형식 '{slug}#{N}'도 지원."""
    # slug#N 형식 처리
    if "#" in str(key_or_id):
        parts = str(key_or_id).split("#", 1)
        slug, num = parts[0], parts[1]
        row = conn.execute(
            "SELECT i.* FROM issues i JOIN projects p ON i.project_id=p.id "
            "WHERE p.slug=? AND i.issue_key=? AND i.deleted_at IS NULL",
            (slug, num)
        ).fetchone()
        return row
    if project_slug:
        row = conn.execute(
            "SELECT i.* FROM issues i JOIN projects p ON i.project_id=p.id "
            "WHERE p.slug=? AND i.issue_key=? AND i.deleted_at IS NULL AND p.deleted_at IS NULL",
            (project_slug, str(key_or_id))
        ).fetchone()
        return row

    # 순수 정수 문자열 → issue_key로 먼저 조회
    rows = conn.execute(
        "SELECT * FROM issues WHERE issue_key=? AND deleted_at IS NULL ORDER BY id", (str(key_or_id),)
    ).fetchall()
    if len(rows) == 1:
        return rows[0]
    if len(rows) > 1:
        return None
    try:
        row = conn.execute(
            "SELECT * FROM issues WHERE id=? AND deleted_at IS NULL", (int(key_or_id),)
        ).fetchone()
        return row
    except ValueError:
        return None

def db_issue_list(conn: sqlite3.Connection, project_id: int,
                  status: str = "", chapter: str = "", category: str = "",
                  assignee: str = "", severity: str = "", search: str = "",
                  sort: str = "default") -> list:
    query = "SELECT * FROM issues WHERE project_id=? AND deleted_at IS NULL"
    params = [project_id]

    if status:
        statuses = [s.strip() for s in status.split(",")]
        placeholders = ",".join(["?"] * len(statuses))
        query += f" AND status IN ({placeholders})"
        params.extend(statuses)
    if chapter:
        query += " AND chapter=?"
        params.append(chapter)
    if category:
        query += " AND category=?"
        params.append(category)
    if assignee:
        query += " AND assignee=?"
        params.append(assignee)
    if severity:
        query += " AND severity=?"
        params.append(severity)
    if search:
        query += " AND (title LIKE ? OR description LIKE ? OR suggestion LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term, term])

    order = "chapter, CAST(issue_key AS INTEGER)"
    if sort == "severity":
        order = ("CASE severity WHEN 'critical' THEN 1 WHEN 'major' THEN 2 "
                 "WHEN 'normal' THEN 3 WHEN 'minor' THEN 4 ELSE 5 END, " + order)
    elif sort == "updated":
        order = "updated_at DESC"
    elif sort == "status":
        order = ("CASE status WHEN 'open' THEN 1 WHEN 'in_progress' THEN 2 "
                 "WHEN 'deferred' THEN 3 WHEN 'resolved' THEN 4 ELSE 5 END, " + order)
    query += f" ORDER BY {order}"

    rows = conn.execute(query, params).fetchall()
    return [
        {
            "issue_key": r["issue_key"],
            "title": r["title"],
            "status": r["status"],
            "severity": r["severity"],
            "category": r["category"],
            "chapter": r["chapter"],
            "assignee": r["assignee"],
            "location": r["location"],
        }
        for r in rows
    ]

def db_issue_show(conn: sqlite3.Connection, key_or_id: str):
    row = db_issue_get(conn, key_or_id)
    if not row:
        return None
    data = row_to_dict(row)
    data["tags"] = [r["tag"] for r in conn.execute(
        "SELECT tag FROM tags WHERE issue_id=? ORDER BY tag", (row["id"],)
    )]
    history_rows = conn.execute(
        "SELECT * FROM issue_history WHERE issue_id=? ORDER BY changed_at",
        (row["id"],)
    ).fetchall()
    data["history"] = [
        {
            "field": h["field"],
            "old_value": h["old_value"],
            "new_value": h["new_value"],
            "changed_by": h["changed_by"],
            "changed_at": h["changed_at"],
            "note": h["note"],
        }
        for h in history_rows
    ]
    return data

def db_issue_update(conn: sqlite3.Connection, issue_id: int, current_row,
                    updates: dict, changed_by: str = "") -> list:
    """updates dict의 필드만 수정. 변경 이력 기록. 변경된 필드 목록 반환."""
    for field, new_val in updates.items():
        record_change(conn, issue_id, field, current_row[field], new_val, changed_by=changed_by)

    set_clause = ", ".join(f"{f}=?" for f in updates)
    set_clause += ", updated_at=datetime('now','localtime')"
    if updates.get("status") == "resolved":
        set_clause += ", resolved_at=datetime('now','localtime')"

    vals = list(updates.values()) + [issue_id]
    conn.execute(f"UPDATE issues SET {set_clause} WHERE id=?", vals)
    conn.commit()
    return list(updates.keys())

# ─── 태그 ─────────────────────────────────────────────────────────────────────

def db_tag_add(conn: sqlite3.Connection, issue_id: int, tags: list):
    for t in tags:
        try:
            conn.execute("INSERT INTO tags(issue_id, tag) VALUES(?,?)", (issue_id, t))
        except sqlite3.IntegrityError:
            pass
    conn.commit()

def db_tag_remove(conn: sqlite3.Connection, issue_id: int, tags: list):
    for t in tags:
        conn.execute("DELETE FROM tags WHERE issue_id=? AND tag=?", (issue_id, t))
    conn.commit()

def db_tag_list(conn: sqlite3.Connection, issue_id: int) -> list:
    return [r["tag"] for r in conn.execute(
        "SELECT tag FROM tags WHERE issue_id=? ORDER BY tag", (issue_id,)
    )]

# ─── 소프트 딜리트 ────────────────────────────────────────────────────────────

def db_project_delete(conn: sqlite3.Connection, slug: str) -> dict:
    """프로젝트에 deleted_at 타임스탬프를 세워 소프트 딜리트한다."""
    p = db_project_get(conn, slug)
    if not p:
        return {"ok": False, "error": f"프로젝트 '{slug}'를 찾을 수 없습니다"}
    conn.execute(
        "UPDATE projects SET deleted_at=datetime('now','localtime') WHERE id=?",
        (p["id"],)
    )
    conn.commit()
    return {"ok": True, "slug": slug, "deleted": True}

def db_issue_delete(conn: sqlite3.Connection, key_or_id: str, deleted_by: str = "") -> dict:
    """이슈에 deleted_at 타임스탬프를 세워 소프트 딜리트한다."""
    row = db_issue_get(conn, key_or_id)
    if not row:
        return {"ok": False, "error": f"이슈 '{key_or_id}'를 찾을 수 없습니다"}
    record_change(conn, row["id"], "deleted_at", None,
                  "datetime('now','localtime')", changed_by=deleted_by)
    conn.execute(
        "UPDATE issues SET deleted_at=datetime('now','localtime'), "
        "updated_at=datetime('now','localtime') WHERE id=?",
        (row["id"],)
    )
    conn.commit()
    return {"ok": True, "issue_key": row["issue_key"], "deleted": True}

# ─── 통계 ─────────────────────────────────────────────────────────────────────

def db_project_stats(conn: sqlite3.Connection, project_id: int) -> dict:
    total = conn.execute(
        "SELECT COUNT(*) FROM issues WHERE project_id=? AND deleted_at IS NULL", (project_id,)
    ).fetchone()[0]

    def group_count(field: str) -> dict:
        rows = conn.execute(
            f"SELECT {field}, COUNT(*) as cnt FROM issues WHERE project_id=? "
            f"AND deleted_at IS NULL AND {field}!='' GROUP BY {field} ORDER BY cnt DESC",
            (project_id,)
        ).fetchall()
        return {r[field]: r["cnt"] for r in rows}

    by_status = {}
    for r in conn.execute(
        "SELECT status, COUNT(*) as cnt FROM issues WHERE project_id=? AND deleted_at IS NULL GROUP BY status",
        (project_id,)
    ):
        by_status[r["status"]] = r["cnt"]

    by_severity = {}
    for r in conn.execute(
        "SELECT severity, COUNT(*) as cnt FROM issues WHERE project_id=? AND deleted_at IS NULL "
        "GROUP BY severity ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'major' THEN 2 "
        "WHEN 'normal' THEN 3 WHEN 'minor' THEN 4 ELSE 5 END",
        (project_id,)
    ):
        by_severity[r["severity"]] = r["cnt"]

    return {
        "total": total,
        "by_status": by_status,
        "by_severity": by_severity,
        "by_category": group_count("category"),
        "by_chapter": group_count("chapter"),
        "by_assignee": group_count("assignee"),
    }

# ─── 임포트 ───────────────────────────────────────────────────────────────────

COLUMN_MAP_RULES = {
    "title":       ("제목", "title", "이슈"),
    "description": ("메모 내용", "설명", "description", "내용", "메모"),
    "category":    ("유형", "category", "카테고리", "분류"),
    "location":    ("위치", "위치/맥락", "location", "맥락"),
    "chapter":     ("장", "chapter", "챕터"),
    "assignee":    ("처리 주체", "담당자", "assignee", "담당"),
    "reporter":    ("작성자", "보고자", "reporter"),
    "suggestion":  ("교정 의견", "suggestion", "제안", "수정 의견"),
    "status":      ("처리상태", "상태", "status"),
    "severity":    ("심각도", "severity"),
}

STATUS_MAP = {
    "처리 완료": "resolved", "완료": "resolved", "resolved": "resolved",
    "저자 확인 필요": "open", "교정자 확인 필요": "open",
    "진행 중": "in_progress", "in_progress": "in_progress",
    "보류": "deferred", "deferred": "deferred",
    "무시": "wontfix", "wontfix": "wontfix",
}

ASSIGNEE_MAP = {
    "저자 확인": "author", "저자": "author",
    "교정자 확인": "editor", "교정자": "editor",
    "처리 완료": "",
}

def build_col_map(columns: list) -> dict:
    col_map = {}
    for c in columns:
        cl = c.strip().lower()
        for field, aliases in COLUMN_MAP_RULES.items():
            if cl in [a.lower() for a in aliases]:
                col_map[field] = c
                break
    return col_map

def db_import_xlsx(conn: sqlite3.Connection, project_id: int,
                   file_path: str, skip_duplicates: bool = False) -> dict:
    try:
        import pandas as pd
    except ImportError:
        return {"ok": False, "error": "pandas가 필요합니다. pip install pandas openpyxl"}

    if not Path(file_path).exists():
        return {"ok": False, "error": f"파일을 찾을 수 없습니다: {file_path}"}

    try:
        df = pd.read_excel(file_path, dtype=str).fillna("")
    except Exception as e:
        return {"ok": False, "error": f"파일 읽기 오류: {e}"}

    col_map = build_col_map(list(df.columns))
    count = 0
    skipped = 0

    for _, r in df.iterrows():
        title = str(r.get(col_map.get("title", ""), "")).strip()
        if not title:
            cat = str(r.get(col_map.get("category", ""), "")).strip()
            loc = str(r.get(col_map.get("location", ""), "")).strip()
            desc_val = str(r.get(col_map.get("description", ""), "")).strip()
            title = f"[{cat}] {loc}" if cat else (desc_val[:60] if desc_val else "제목 없음")

        desc     = str(r.get(col_map.get("description", ""), "")).strip()
        cat      = str(r.get(col_map.get("category", ""), "")).strip()
        loc      = str(r.get(col_map.get("location", ""), "")).strip()
        ch       = str(r.get(col_map.get("chapter", ""), "")).strip()
        assignee_raw = str(r.get(col_map.get("assignee", ""), "")).strip()
        assignee = ASSIGNEE_MAP.get(assignee_raw, assignee_raw)
        reporter_raw = str(r.get(col_map.get("reporter", ""), "claude")).strip()
        reporter = reporter_raw.lower() if reporter_raw else "claude"
        suggestion   = str(r.get(col_map.get("suggestion", ""), "")).strip()
        status_raw   = str(r.get(col_map.get("status", ""), "open")).strip()
        status       = STATUS_MAP.get(status_raw, "open")
        severity_raw = str(r.get(col_map.get("severity", ""), "normal")).strip()
        severity     = severity_raw if severity_raw in VALID_SEVERITIES else "normal"

        if skip_duplicates:
            dup = conn.execute(
                "SELECT id FROM issues WHERE project_id=? AND description=? AND location=?",
                (project_id, desc, loc)
            ).fetchone()
            if dup:
                skipped += 1
                continue

        key = next_issue_key(conn, project_id)
        conn.execute(
            """INSERT INTO issues(project_id, issue_key, title, description, status, category,
               severity, location, chapter, assignee, reporter, suggestion, source)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (project_id, key, title, desc, status, cat, severity, loc, ch,
             assignee, reporter, suggestion, "import")
        )
        count += 1

    conn.commit()
    return {"ok": True, "imported": count, "skipped": skipped}

# ─── 익스포트 ─────────────────────────────────────────────────────────────────

EXPORT_COLUMNS = [
    "issue_key", "title", "description", "status", "category", "severity",
    "location", "chapter", "assignee", "reporter", "suggestion", "resolution",
    "source", "created_at", "updated_at", "resolved_at",
]

def db_export_issues(conn: sqlite3.Connection, project_id: int,
                     output_path: str, status_filter: str = "") -> dict:
    query = "SELECT * FROM issues WHERE project_id=? AND deleted_at IS NULL"
    params = [project_id]
    if status_filter:
        statuses = [s.strip() for s in status_filter.split(",")]
        placeholders = ",".join(["?"] * len(statuses))
        query += f" AND status IN ({placeholders})"
        params.extend(statuses)
    query += " ORDER BY CAST(issue_key AS INTEGER)"

    rows = conn.execute(query, params).fetchall()
    if not rows:
        return {"ok": False, "error": "내보낼 이슈가 없습니다"}

    out = Path(output_path)
    fmt = out.suffix.lstrip(".")

    try:
        if fmt == "xlsx":
            import pandas as pd
            data = [{c: r[c] for c in EXPORT_COLUMNS} for r in rows]
            pd.DataFrame(data).to_excel(output_path, index=False)
        elif fmt == "json":
            data = [{c: r[c] for c in EXPORT_COLUMNS} for r in rows]
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        else:  # csv 기본
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=EXPORT_COLUMNS)
                writer.writeheader()
                for r in rows:
                    writer.writerow({c: r[c] for c in EXPORT_COLUMNS})
            fmt = "csv"
    except ImportError:
        return {"ok": False, "error": "pandas, openpyxl이 필요합니다. pip install pandas openpyxl"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    return {"ok": True, "path": output_path, "count": len(rows), "format": fmt}
