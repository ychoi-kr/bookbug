#!/usr/bin/env python3
"""bookbug_web — 출판 원고 교정 이슈 트래커 웹 인터페이스

FastAPI + Jinja2. 포트 8420.
bookbug_db.py를 직접 import하여 사용 (MCP 서버 불필요).
"""

import sys
import os
import re as _re
import json as _json
from markupsafe import Markup, escape
sys.path.insert(0, os.path.dirname(__file__))

from typing import Optional
from fastapi import FastAPI, Request, Form, Query, HTTPException
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

# ─── LAN 접근 판별 ────────────────────────────────────────────────────────────

LAN_PREFIXES = ("172.30.", "192.168.", "10.", "127.")

def _is_lan(request: Request) -> bool:
    """요청이 LAN에서 왔으면 True. Cloudflare Tunnel 경유 시 False."""
    ip = request.client.host if request.client else ""
    return any(ip.startswith(p) for p in LAN_PREFIXES)

def _readonly(request: Request) -> bool:
    return not _is_lan(request)

def _require_write(request: Request):
    """쓰기 전용 엔드포인트 앞에서 호출. 읽기 전용이면 403."""
    if _readonly(request):
        raise HTTPException(status_code=403, detail="읽기 전용 접근입니다. LAN에서만 수정할 수 있습니다.")

# ─────────────────────────────────────────────────────────────────────────────

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
    "major":    ("major",    "warning"),
    "normal":   ("normal",   "secondary"),
    "minor":    ("minor",    "info"),
}

def label(mapping, key):
    text, color = mapping.get(key, (key, "secondary"))
    return {"text": text, "color": color}

FIELD_LABEL = {
    "title":       "제목",
    "description": "문제 내용",
    "suggestion":  "교정 의견",
    "resolution":  "처리 내용",
    "status":      "상태",
    "severity":    "심각도",
    "category":    "유형",
    "heading_no":     "제목 번호",
    "location":    "위치",
    "assignee":    "담당자",
    "reporter":    "보고자",
    "manuscript_ver":      "원고 파일",
    "deleted_at":  "삭제",
}

LONG_FIELDS = {"description", "suggestion", "resolution", "title"}

templates.env.globals["status_label"]   = lambda k: label(STATUS_LABEL, k)
templates.env.globals["severity_label"] = lambda k: label(SEVERITY_LABEL, k)
templates.env.globals["VALID_STATUSES"]   = VALID_STATUSES
templates.env.globals["VALID_SEVERITIES"] = VALID_SEVERITIES
templates.env.globals["FIELD_LABEL"]      = FIELD_LABEL


def parse_suggestion(value):
    """suggestion 필드를 JSON으로 파싱. 실패 시 플레인 텍스트로 반환."""
    if not value:
        return None
    try:
        parsed = _json.loads(value)
        if isinstance(parsed, dict):
            parsed.setdefault("items", [])
            return parsed
    except (_json.JSONDecodeError, ValueError):
        pass
    return {"summary": value, "items": []}


def linkify_refs(text, project_slug=""):
    """텍스트에서 #N 또는 slug#N 패턴을 이슈 링크로 변환.
    원본 텍스트에 regex를 먼저 적용하고 나머지 부분만 HTML escape해야
    &#34; 같은 엔티티가 이슈 번호로 오인되지 않는다.
    """
    if not text:
        return text
    pattern = _re.compile(r'([A-Za-z][A-Za-z0-9_-]*)#(\d+)|(?<![A-Za-z0-9_-])#(\d+)')
    result = Markup()
    last = 0
    for m in pattern.finditer(text):
        result += escape(text[last:m.start()])
        if m.group(1):  # slug#N
            slug = m.group(1)
            n    = m.group(2)
            result += Markup(f'<a href="/issue/{slug}/{n}">{slug}#{n}</a>')
        else:           # #N
            n = m.group(3)
            href = f"/issue/{project_slug}/{n}" if project_slug else "#"
            result += Markup(f'<a href="{href}">#{n}</a>')
        last = m.end()
    result += escape(text[last:])
    return result

templates.env.filters["linkify_refs"] = linkify_refs


# ─── 프로젝트 목록 ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    with get_db() as conn:
        projects = db_project_list(conn)
    return templates.TemplateResponse(request, "projects.html", {
        "projects": projects,
        "readonly": _readonly(request),
    })


# ─── 이슈 목록 ─────────────────────────────────────────────────────────────────

@app.get("/project/{slug}", response_class=HTMLResponse)
def project_view(
    request: Request,
    slug: str,
    status:   str = Query(""),
    category: str = Query(""),
    assignee: str = Query(""),
    severity: str = Query(""),
    search:   str = Query(""),
    sort:     str = Query("default"),
    page:     int = Query(1),
):
    PAGE_SIZE = 50
    # 콤마 구분 → 리스트 (템플릿용)
    status_list   = [s for s in status.split(",")   if s] if status   else []
    severity_list = [s for s in severity.split(",") if s] if severity else []

    with get_db() as conn:
        p = db_project_get(conn, slug)
        if not p:
            return HTMLResponse("프로젝트를 찾을 수 없습니다.", status_code=404)
        issues = db_issue_list(conn, p["id"], status, "", category, assignee, severity, search, sort)
        stats  = db_project_stats(conn, p["id"])

        # 필터 옵션 목록 (동적)
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
            "status": status, "status_list": status_list,
            "category": category,
            "assignee": assignee,
            "severity": severity, "severity_list": severity_list,
            "search": search, "sort": sort,
        },
        "options": {
            "categories": all_categories,
            "assignees": all_assignees,
        },
        "readonly": _readonly(request),
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
    SHORT_FIELDS = {"status", "severity", "assignee", "category", "heading_no", "reporter", "manuscript_ver"}
    grouped_history = []
    for (changed_at, changed_by), items in groupby(
        history, key=lambda h: (h["changed_at"], h["changed_by"])
    ):
        entries = list(items)
        short = [e for e in entries if e["field"] in SHORT_FIELDS]
        long  = [e for e in entries if e["field"] not in SHORT_FIELDS]
        # long 항목에 한국어 레이블 추가
        for e in long:
            e["field_label"] = FIELD_LABEL.get(e["field"], e["field"])
        grouped_history.append({
            "changed_at": changed_at,
            "changed_by": changed_by,
            "note": entries[0].get("note", "") if entries else "",
            "short": short,
            "long": long,
        })

    suggestion_parsed = parse_suggestion(data.get("suggestion", ""))

    return templates.TemplateResponse(request, "issue.html", {
        "issue": data,
        "tags": tags,
        "history": history,
        "grouped_history": grouped_history,
        "SHORT_FIELDS": SHORT_FIELDS,
        "back_url": back_url,
        "suggestion_parsed": suggestion_parsed,
        "readonly": _readonly(request),
    })


# ─── 이슈 수정 폼 ──────────────────────────────────────────────────────────────

@app.get("/issue/{slug}/{num}/edit", response_class=HTMLResponse)
def issue_edit_form(request: Request, slug: str, num: str, back: str = ""):
    from urllib.parse import unquote
    _require_write(request)
    ref = f"{slug}#{num}"
    with get_db() as conn:
        row = db_issue_get(conn, ref)
        if not row:
            return HTMLResponse("이슈를 찾을 수 없습니다.", status_code=404)
        issue = dict(row)
        issue["project_slug"] = slug
    return templates.TemplateResponse(request, "issue_edit.html", {
        "issue": issue,
        "back_url": unquote(back) if back else "",
    })


@app.post("/issue/{slug}/{num}/edit")
async def issue_edit_submit(
    request: Request,
    slug: str,
    num: str,
    title:       str = Form(""),
    status:      str = Form(""),
    category:    str = Form(""),
    severity:    str = Form(""),
    location:    str = Form(""),
    heading_no:     str = Form(""),
    assignee:       str = Form(""),
    manuscript_ver: str = Form(""),
    suggestion:     str = Form(""),
    resolution:     str = Form(""),
    changed_by:     str = Form("editor"),
    back:           str = Form(""),
):
    _require_write(request)
    ref = f"{slug}#{num}"
    if suggestion:
        suggestion = _json.dumps(parse_suggestion(suggestion), ensure_ascii=False)
    updates = {}
    fields = {
        "title": title, "status": status,
        "category": category, "severity": severity, "location": location,
        "heading_no": heading_no, "assignee": assignee, "manuscript_ver": manuscript_ver, "suggestion": suggestion,
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
    from urllib.parse import quote
    back_param = f"?back={quote(back)}" if back else ""
    return RedirectResponse(f"/issue/{slug}/{num}{back_param}", status_code=303)


# ─── 빠른 상태 변경 (이슈 목록에서 인라인) ────────────────────────────────────

@app.post("/issue/{slug}/{num}/status")
async def issue_status_update(
    request: Request,
    slug: str,
    num: str,
    status:     str = Form(...),
    changed_by: str = Form("editor"),
    back:       str = Form(""),
):
    _require_write(request)
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
