#!/usr/bin/env python3
"""bookbug_web — 출판 원고 교정 이슈 트래커 웹 인터페이스

FastAPI + Jinja2. 포트 8420.
bookbug_db.py를 직접 import하여 사용 (MCP 서버 불필요).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from typing import Optional
from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import uvicorn

from bookbug_db import (
    get_db,
    db_project_create,
    db_project_list,
    db_project_show,
    db_project_stats,
    db_project_get,
    db_issue_add,
    db_issue_get,
    db_issue_list,
    db_issue_show,
    db_issue_update,
    db_export_issues,
    VALID_STATUSES,
    VALID_SEVERITIES,
)

BASE_DIR = os.path.dirname(__file__)

app = FastAPI(title="bookbug", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


# ─── 헬퍼 ─────────────────────────────────────────────────────────────────────

STATUS_LABEL = {
    "open":        ("열림",   "secondary"),
    "in_progress": ("진행",   "primary"),
    "resolved":    ("해결",   "success"),
    "wontfix":     ("유지",   "warning"),
    "deferred":    ("보류",   "secondary"),
    "duplicate":   ("중복",   "info"),
}

SEVERITY_LABEL = {
    "critical": ("critical", "danger"),
    "high":     ("high",     "warning"),
    "normal":   ("normal",   "secondary"),
    "low":      ("low",      "light"),
}

def label(mapping, key):
    text, color = mapping.get(key, (key, "secondary"))
    return {"text": text, "color": color}

templates.env.globals["status_label"]   = lambda k: label(STATUS_LABEL, k)
templates.env.globals["severity_label"] = lambda k: label(SEVERITY_LABEL, k)
templates.env.globals["VALID_STATUSES"]   = VALID_STATUSES
templates.env.globals["VALID_SEVERITIES"] = VALID_SEVERITIES


# ─── 프로젝트 목록 ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    with get_db() as conn:
        projects = db_project_list(conn)
    return templates.TemplateResponse(request, "projects.html", {"projects": projects})


# ─── 이슈 목록 ─────────────────────────────────────────────────────────────────

@app.get("/project/{slug}", response_class=HTMLResponse)
def project_view(
    request: Request,
    slug: str,
    status:   str = Query(""),
    chapter:  str = Query(""),
    category: str = Query(""),
    assignee: str = Query(""),
    severity: str = Query(""),
    search:   str = Query(""),
    sort:     str = Query("default"),
    page:     int = Query(1),
):
    PAGE_SIZE = 50
    with get_db() as conn:
        p = db_project_get(conn, slug)
        if not p:
            return HTMLResponse("프로젝트를 찾을 수 없습니다.", status_code=404)
        issues = db_issue_list(conn, p["id"], status, chapter, category, assignee, severity, search, sort)
        stats  = db_project_stats(conn, p["id"])

        # 필터 옵션 목록 (동적)
        all_chapters  = sorted({i["chapter"]  for i in db_issue_list(conn, p["id"]) if i["chapter"]})
        all_categories = sorted({i["category"] for i in db_issue_list(conn, p["id"]) if i["category"]})
        all_assignees  = sorted({i["assignee"] for i in db_issue_list(conn, p["id"]) if i["assignee"]})

    total = len(issues)
    start = (page - 1) * PAGE_SIZE
    page_issues = issues[start:start + PAGE_SIZE]
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    return templates.TemplateResponse(request, "project.html", {
        "project": p,
        "issues": page_issues,
        "stats": stats,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "filters": {
            "status": status, "chapter": chapter, "category": category,
            "assignee": assignee, "severity": severity, "search": search, "sort": sort,
        },
        "options": {
            "chapters": all_chapters,
            "categories": all_categories,
            "assignees": all_assignees,
        },
    })


# ─── 이슈 상세 ─────────────────────────────────────────────────────────────────

@app.get("/issue/{slug}/{num}", response_class=HTMLResponse)
def issue_view(request: Request, slug: str, num: str, back: str = ""):
    from urllib.parse import unquote
    back_url = unquote(back) if back else ""
    ref = f"{slug}#{num}"
    with get_db() as conn:
        data = db_issue_show(conn, ref)
        if not data:
            return HTMLResponse("이슈를 찾을 수 없습니다.", status_code=404)
        data["project_slug"] = slug
        p = db_project_get(conn, slug)
        data["project_title"] = p["title"] if p else slug
    tags    = data.pop("tags", [])
    history = data.pop("history", [])

    # 같은 changed_at + changed_by 묶기 (GitHub 스타일 이벤트 그룹)
    from itertools import groupby
    SHORT_FIELDS = {"status", "severity", "assignee", "category", "chapter", "reporter", "source"}
    grouped_history = []
    for (changed_at, changed_by), items in groupby(
        history, key=lambda h: (h["changed_at"], h["changed_by"])
    ):
        entries = list(items)
        short = [e for e in entries if e["field"] in SHORT_FIELDS]
        long  = [e for e in entries if e["field"] not in SHORT_FIELDS]
        grouped_history.append({
            "changed_at": changed_at,
            "changed_by": changed_by,
            "short": short,
            "long": long,
        })

    return templates.TemplateResponse(request, "issue.html", {
        "issue": data,
        "tags": tags,
        "history": history,
        "grouped_history": grouped_history,
        "SHORT_FIELDS": SHORT_FIELDS,
        "back_url": back_url,
    })


# ─── 이슈 수정 폼 ──────────────────────────────────────────────────────────────

@app.get("/issue/{slug}/{num}/edit", response_class=HTMLResponse)
def issue_edit_form(request: Request, slug: str, num: str):
    ref = f"{slug}#{num}"
    with get_db() as conn:
        row = db_issue_get(conn, ref)
        if not row:
            return HTMLResponse("이슈를 찾을 수 없습니다.", status_code=404)
        issue = dict(row)
        issue["project_slug"] = slug
    return templates.TemplateResponse(request, "issue_edit.html", {
        "issue": issue,
    })


@app.post("/issue/{slug}/{num}/edit")
async def issue_edit_submit(
    request: Request,
    slug: str,
    num: str,
    title:       str = Form(""),
    description: str = Form(""),
    status:      str = Form(""),
    category:    str = Form(""),
    severity:    str = Form(""),
    location:    str = Form(""),
    chapter:     str = Form(""),
    assignee:    str = Form(""),
    suggestion:  str = Form(""),
    resolution:  str = Form(""),
    changed_by:  str = Form("editor"),
):
    ref = f"{slug}#{num}"
    updates = {}
    fields = {
        "title": title, "description": description, "status": status,
        "category": category, "severity": severity, "location": location,
        "chapter": chapter, "assignee": assignee, "suggestion": suggestion,
        "resolution": resolution,
    }
    with get_db() as conn:
        row = db_issue_get(conn, ref)
        if not row:
            return HTMLResponse("이슈를 찾을 수 없습니다.", status_code=404)
        for field, val in fields.items():
            if val and val != dict(row).get(field, ""):
                updates[field] = val
        if updates:
            db_issue_update(conn, row["id"], row, updates, changed_by=changed_by)
    return RedirectResponse(f"/issue/{slug}/{num}", status_code=303)


# ─── 빠른 상태 변경 (이슈 목록에서 인라인) ────────────────────────────────────

@app.post("/issue/{slug}/{num}/status")
async def issue_status_update(
    slug: str,
    num: str,
    status:     str = Form(...),
    changed_by: str = Form("editor"),
    back:       str = Form(""),
):
    ref = f"{slug}#{num}"
    with get_db() as conn:
        row = db_issue_get(conn, ref)
        if row:
            db_issue_update(conn, row["id"], row, {"status": status}, changed_by=changed_by)
    dest = back if back else f"/issue/{slug}/{num}"
    return RedirectResponse(dest, status_code=303)


# ─── export (JSON) ─────────────────────────────────────────────────────────────
# 나중에 xlsx/csv export 붙이기 쉽도록 라우트 미리 분리

@app.get("/project/{slug}/export")
def project_export(
    slug: str,
    fmt:    str = Query("json"),
    status: str = Query(""),
):
    import tempfile, json
    with get_db() as conn:
        p = db_project_get(conn, slug)
        if not p:
            return JSONResponse({"error": "프로젝트 없음"}, status_code=404)
        if fmt in ("xlsx", "csv"):
            with tempfile.NamedTemporaryFile(suffix=f".{fmt}", delete=False) as f:
                tmp_path = f.name
            result = db_export_issues(conn, p["id"], tmp_path, status)
            if not result.get("ok"):
                return JSONResponse(result, status_code=500)
            from fastapi.responses import FileResponse
            filename = f"{slug}_issues.{fmt}"
            return FileResponse(tmp_path, filename=filename,
                                media_type="application/octet-stream")
        else:
            # JSON: 직접 반환
            issues = db_issue_list(conn, p["id"], status=status)
    return JSONResponse({"project": slug, "count": len(issues), "issues": issues})


# ─── 진입점 ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("bookbug_web:app", host="0.0.0.0", port=8420, reload=True)
