#!/usr/bin/env python3
"""bookbug_mcp — 출판 원고 교정용 이슈 트래커 MCP 서버

FastMCP + Streamable HTTP 기반. 포트 8419.
DB 위치: ~/.bookbug/bookbug.db
"""

import json as _json
from typing import Optional
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from bookbug_db import (
    get_db,
    db_project_create,
    db_project_list,
    db_project_show,
    db_project_stats,
    db_project_get,
    db_project_delete,
    db_issue_add,
    db_issue_get,
    db_issue_list,
    db_issue_show,
    db_issue_update,
    db_issue_amend,
    db_issue_delete,
    db_tag_add,
    db_tag_remove,
    db_tag_list,
    db_import_xlsx,
    db_export_issues,
    VALID_STATUSES,
    VALID_SEVERITIES,
)

def _parse_suggestion(value: str) -> str:
    """suggestion 입력값을 JSON 구조로 정규화.
    이미 유효한 JSON이면 그대로, 플레인 텍스트면 summary로 래핑.
    """
    if not value:
        return value
    try:
        parsed = _json.loads(value)
        if isinstance(parsed, dict) and "summary" in parsed:
            return value  # 이미 올바른 구조
        raise ValueError
    except (ValueError, _json.JSONDecodeError):
        # 플레인 텍스트 → summary로 래핑
        wrapped = {"summary": value, "items": []}
        return _json.dumps(wrapped, ensure_ascii=False)


mcp = FastMCP(
    name="bookbug",
    instructions="출판 원고 교정용 이슈 트래커",
)



def _resolve_issue(conn, issue: str, project: str = ""):
    """issue 참조를 안전하게 해석한다. 프로젝트 간 키 충돌을 감지한다.
    이슈를 찾으면 row를 반환, 못 찾으면 ToolError를 raise한다."""
    if project:
        p = db_project_get(conn, project)
        if not p:
            raise ToolError(f"프로젝트 '{project}'를 찾을 수 없습니다")
        row = db_issue_get(conn, issue, project_slug=project)
        if not row:
            raise ToolError(f"프로젝트 '{project}'에서 이슈 '{issue}'를 찾을 수 없습니다")
        return row

    row = db_issue_get(conn, issue)
    if row:
        return row

    if "#" not in str(issue):
        conflict = conn.execute(
            "SELECT COUNT(*) FROM issues WHERE issue_key=? AND deleted_at IS NULL",
            (str(issue),)
        ).fetchone()[0]
        if conflict > 1:
            raise ToolError(
                f"이슈 키 '{issue}'가 여러 프로젝트에 존재합니다. "
                "project 파라미터를 지정하거나 'slug#issue_key' 형식을 사용해 주세요"
            )

    raise ToolError(f"이슈 '{issue}'를 찾을 수 없습니다")

# ─── 프로젝트 관리 ─────────────────────────────────────────────────────────────

@mcp.tool()
def project_create(slug: str, title: str, description: str = "", base_path: str = "") -> dict:
    """프로젝트를 생성한다."""
    with get_db() as conn:
        return db_project_create(conn, slug, title, description, base_path)


@mcp.tool()
def project_list() -> dict:
    """전체 프로젝트 목록과 이슈 수 요약을 반환한다."""
    with get_db() as conn:
        return {"projects": db_project_list(conn)}


@mcp.tool()
def project_show(slug: str) -> dict:
    """프로젝트 상세 정보와 상태별 이슈 집계를 반환한다."""
    with get_db() as conn:
        result = db_project_show(conn, slug)
    if result is None:
        return {"ok": False, "error": f"프로젝트 '{slug}'를 찾을 수 없습니다"}
    return result


@mcp.tool()
def project_delete(slug: str) -> dict:
    """프로젝트를 소프트 딜리트한다. 데이터는 보존되며 목록에서만 숨겨진다."""
    with get_db() as conn:
        return db_project_delete(conn, slug)

# ─── 이슈 CRUD ────────────────────────────────────────────────────────────────

@mcp.tool()
def issue_add(
    project: str,
    title: str,
    description: str = "",
    category: str = "",
    severity: str = "normal",
    location: str = "",
    heading_no: str = "",
    assignee: str = "",
    reporter: str = "claude",
    suggestion: str = "",
    manuscript: str = "",
) -> dict:
    """새 이슈를 등록한다. issue_key는 자동 생성.

    severity 값: critical / major / normal(기본) / minor / trivial
    description: 문제 상황 기술. 원고의 어떤 부분이 왜 문제인지 사실 중심으로 기록.
    suggestion: 교정 의견. JSON 구조로 입력:
      {"summary": "전체 요약", "items": [{"before_desc": "...", "before": "...", "after_desc": "...", "after": "..."}]}
      - summary: 교정 의견 전체 요약 (필수)
      - items: 수정 위치별 목록 (복수 가능, 각 필드 모두 optional)
        - before_desc: 수정 전 설명 (위치, 문제점)
        - before: 수정 전 원고 본문
        - after_desc: 수정 후 설명
        - after: 수정 후 원고 본문 (복사/붙여넣기 대상)
      플레인 텍스트 입력 시 자동으로 summary에 래핑됨.
    manuscript: 이슈를 발견한 원고 파일명 또는 URL.
      예) 원고_20260326.docx, CS면접_1부_1교_20260303.docx, https://wikidocs.net/12345
    (resolution은 처리 후 issue_update로 별도 기입)
    """
    if severity not in VALID_SEVERITIES:
        return {"ok": False, "error": f"유효하지 않은 심각도: '{severity}'. 허용값: {', '.join(VALID_SEVERITIES)}"}
    suggestion = _parse_suggestion(suggestion)
    with get_db() as conn:
        p = db_project_get(conn, project)
        if not p:
            return {"ok": False, "error": f"프로젝트 '{project}'를 찾을 수 없습니다"}
        return db_issue_add(
            conn, p["id"], title, description, category,
            severity, location, heading_no, assignee, reporter, suggestion, manuscript
        )


@mcp.tool()
def issue_list(
    project: str,
    status: str = "",
    heading_no: str = "",
    category: str = "",
    assignee: str = "",
    severity: str = "",
    search: str = "",
    sort: str = "default",
) -> dict:
    """프로젝트의 이슈 목록을 필터링하여 반환한다.

    모든 필터는 선택 사항이며 조합 가능. 미지정 시 전체 반환.
    status: 쉼표 구분으로 복수 지정 가능 (예: "open,in_progress")
    severity: 쉼표 구분으로 복수 지정 가능 (예: "critical,major")
    heading_no: 장 번호로 필터
    category: 카테고리로 필터
    assignee: 담당자로 필터
    search: title, description, suggestion에서 텍스트 검색
    sort: default / severity / status / updated / created / key_asc / key_desc
    """
    with get_db() as conn:
        p = db_project_get(conn, project)
        if not p:
            return {"ok": False, "error": f"프로젝트 '{project}'를 찾을 수 없습니다"}
        issues = db_issue_list(conn, p["id"], status, heading_no, category, assignee, severity, search, sort)
    return {"project": project, "count": len(issues), "issues": issues}


@mcp.tool()
def issue_show(issue: str, project: str = "") -> dict:
    """이슈의 전체 상세 정보를 반환한다. 태그와 변경 이력 포함."""
    with get_db() as conn:
        row = _resolve_issue(conn, issue, project)
        ref = f"{project}#{row['issue_key']}" if project else issue
        data = db_issue_show(conn, ref)
    return data


@mcp.tool()
def issue_update(
    issue: str,
    project: str = "",
    title: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    location: Optional[str] = None,
    heading_no: Optional[str] = None,
    assignee: Optional[str] = None,
    suggestion: Optional[str] = None,
    resolution: Optional[str] = None,
    changed_by: str = "",
) -> dict:
    """이슈의 필드를 수정한다. 변경 이력 자동 기록. 전달된 파라미터만 수정.

    description(문제 내용)은 수정 불가 — 잘못 작성된 경우 issue_amend를 사용.
      추가 분석이나 논리는 description이 아닌 suggestion에 기입할 것.
    교정 의견은 suggestion(JSON 구조), 처리 내용은 resolution 필드를 사용.
    suggestion 형식: {"summary": "...", "items": [{"before_desc","before","after_desc","after"}]}

    status 값: open / in_progress / resolved / wontfix / deferred / duplicate
    severity 값: critical / major / normal / minor / trivial
    """
    if suggestion is not None:
        suggestion = _parse_suggestion(suggestion)
    updates = {}
    for field, val in [
        ("title", title), ("status", status),
        ("category", category), ("severity", severity), ("location", location),
        ("heading_no", heading_no), ("assignee", assignee), ("suggestion", suggestion),
        ("resolution", resolution),
    ]:
        if val is not None:
            updates[field] = val

    if not updates:
        return {"ok": False, "error": "변경할 항목을 하나 이상 지정해 주세요"}
    if "status" in updates and updates["status"] not in VALID_STATUSES:
        return {"ok": False, "error": f"유효하지 않은 상태: '{updates['status']}'. 허용값: {', '.join(VALID_STATUSES)}"}
    if "severity" in updates and updates["severity"] not in VALID_SEVERITIES:
        return {"ok": False, "error": f"유효하지 않은 심각도: '{updates['severity']}'. 허용값: {', '.join(VALID_SEVERITIES)}"}

    with get_db() as conn:
        row = _resolve_issue(conn, issue, project)
        updated_fields = db_issue_update(conn, row["id"], row, updates, changed_by)
    return {"ok": True, "issue_key": row["issue_key"], "updated_fields": updated_fields}


@mcp.tool()
def issue_amend(issue: str, project: str = "", description: str = "", amended_by: str = "") -> dict:
    """이슈의 문제 내용(description)을 정정한다.

    최초 등록 시 잘못 작성된 경우에만 사용. 변경 이력에 'amend'로 기록된다.
    교정 의견 추가는 issue_update의 suggestion 파라미터를 사용.
    """
    if not description:
        raise ToolError("정정할 내용(description)을 입력해 주세요")
    with get_db() as conn:
        row = _resolve_issue(conn, issue, project)
        db_issue_amend(conn, row["id"], row, description, changed_by=amended_by)
    return {"ok": True, "issue_key": row["issue_key"], "amended": True}



@mcp.tool()
def issue_delete(issue: str, deleted_by: str = "") -> dict:
    """이슈를 소프트 딜리트한다. 데이터는 보존되며 목록에서 숨겨진다."""
    with get_db() as conn:
        return db_issue_delete(conn, issue, deleted_by)

# ─── 일괄 처리 ────────────────────────────────────────────────────────────────

@mcp.tool()
def issue_bulk_update(updates: str, changed_by: str = "", project: str = "") -> dict:
    """여러 이슈를 한 번에 업데이트한다. 1회 트랜잭션으로 처리.
    updates: JSON 배열. 각 항목에 issue(필수)와 변경할 필드를 지정.
    예시: [{"issue":"BUG#1","status":"resolved"},{"issue":"BUG#2","severity":"major","assignee":"홍길동"}]
    허용 필드: title, status, category, severity, location, heading_no, assignee, suggestion, resolution
    status 값: open / in_progress / resolved / wontfix / deferred / duplicate
    severity 값: critical / major / normal / minor / trivial
    """
    try:
        items = _json.loads(updates)
    except (ValueError, _json.JSONDecodeError):
        return {"ok": False, "error": "updates는 유효한 JSON 배열이어야 합니다"}
    if not isinstance(items, list):
        return {"ok": False, "error": "updates는 JSON 배열이어야 합니다"}

    ALLOWED_FIELDS = {"title", "status", "category", "severity", "location",
                      "heading_no", "assignee", "suggestion", "resolution"}
    results = []
    with get_db() as conn:
        for item in items:
            issue_ref = item.get("issue")
            if not issue_ref:
                results.append({"issue": None, "ok": False, "error": "issue 키 누락"})
                continue
            row = db_issue_get(conn, str(issue_ref), project_slug=project)
            if not row:
                results.append({"issue": issue_ref, "ok": False, "error": "이슈를 찾을 수 없습니다"})
                continue
            fields = {k: v for k, v in item.items() if k in ALLOWED_FIELDS}
            if not fields:
                results.append({"issue": issue_ref, "ok": False, "error": "변경할 필드 없음"})
                continue
            if "status" in fields and fields["status"] not in VALID_STATUSES:
                results.append({"issue": issue_ref, "ok": False,
                                "error": f"유효하지 않은 상태: '{fields['status']}'"})
                continue
            if "severity" in fields and fields["severity"] not in VALID_SEVERITIES:
                results.append({"issue": issue_ref, "ok": False,
                                "error": f"유효하지 않은 심각도: '{fields['severity']}'"})
                continue
            if "suggestion" in fields:
                fields["suggestion"] = _parse_suggestion(fields["suggestion"])
            updated = db_issue_update(conn, row["id"], row, fields,
                                      changed_by=changed_by, auto_commit=False)
            results.append({"issue": issue_ref, "ok": True, "updated_fields": updated})
        conn.commit()

    succeeded = sum(1 for r in results if r.get("ok"))
    failed = sum(1 for r in results if not r.get("ok"))
    return {"ok": True, "total": len(items), "succeeded": succeeded,
            "failed": failed, "details": results}

# ─── 태그 ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def issue_tag(issue: str, action: str, tags: str = "") -> dict:
    """이슈에 태그를 추가/제거/조회한다. action: add/remove/list"""
    if action not in ("add", "remove", "list"):
        return {"ok": False, "error": f"유효하지 않은 action: '{action}'. 허용값: add, remove, list"}
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    if action in ("add", "remove") and not tag_list:
        return {"ok": False, "error": f"{action}할 태그를 지정해 주세요"}

    with get_db() as conn:
        row = db_issue_get(conn, issue)
        if not row:
            return {"ok": False, "error": f"이슈 '{issue}'를 찾을 수 없습니다"}
        if action == "add":
            db_tag_add(conn, row["id"], tag_list)
        elif action == "remove":
            db_tag_remove(conn, row["id"], tag_list)
        current_tags = db_tag_list(conn, row["id"])
    return {"issue_key": row["issue_key"], "tags": current_tags}

# ─── 임포트/익스포트 ──────────────────────────────────────────────────────────

@mcp.tool()
def import_xlsx(project: str, file_path: str, skip_duplicates: bool = False) -> dict:
    """엑셀 파일에서 이슈를 임포트한다."""
    with get_db() as conn:
        p = db_project_get(conn, project)
        if not p:
            return {"ok": False, "error": f"프로젝트 '{project}'를 찾을 수 없습니다"}
        return db_import_xlsx(conn, p["id"], file_path, skip_duplicates)


@mcp.tool()
def export_issues(project: str, output_path: str, status: str = "") -> dict:
    """이슈를 파일로 내보낸다. output_path: .xlsx/.csv/.json"""
    with get_db() as conn:
        p = db_project_get(conn, project)
        if not p:
            return {"ok": False, "error": f"프로젝트 '{project}'를 찾을 수 없습니다"}
        return db_export_issues(conn, p["id"], output_path, status)

# ─── 통계/이력/검색 ───────────────────────────────────────────────────────────

@mcp.tool()
def project_stats(project: str) -> dict:
    """프로젝트의 이슈 통계를 반환한다."""
    with get_db() as conn:
        p = db_project_get(conn, project)
        if not p:
            return {"ok": False, "error": f"프로젝트 '{project}'를 찾을 수 없습니다"}
        return db_project_stats(conn, p["id"])


@mcp.tool()
def issue_history(issue: str, project: str = "") -> dict:
    """특정 이슈의 변경 이력을 반환한다."""
    with get_db() as conn:
        row = _resolve_issue(conn, issue, project)
        history_rows = conn.execute(
            "SELECT * FROM issue_history WHERE issue_id=? ORDER BY changed_at",
            (row["id"],)
        ).fetchall()
        history = [
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
    return {"issue_key": row["issue_key"], "history": history}


@mcp.tool()
def search_issues(query: str, project: str = "") -> dict:
    """전체 프로젝트 또는 특정 프로젝트에서 텍스트를 검색한다.

    title, description, suggestion, resolution, location을 대상으로 검색.
    project 미지정 시 모든 프로젝트에서 검색.
    특정 프로젝트 내에서 필터 조합이 필요하면 issue_list의 search 파라미터를 사용.
    """
    term = f"%{query}%"
    sql = (
        "SELECT i.*, p.slug as project_slug FROM issues i "
        "JOIN projects p ON i.project_id=p.id "
        "WHERE i.deleted_at IS NULL AND p.deleted_at IS NULL "
        "AND (i.title LIKE ? OR i.description LIKE ? OR i.suggestion LIKE ? "
        "OR i.resolution LIKE ? OR i.location LIKE ?)"
    )
    params = [term] * 5
    if project:
        sql += " AND p.slug=?"
        params.append(project)
    sql += " ORDER BY i.updated_at DESC"

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    results = [
        {
            "project": r["project_slug"],
            "issue_key": r["issue_key"],
            "title": r["title"],
            "status": r["status"],
            "category": r["category"],
            "heading_no": r["heading_no"],
            "location": r["location"],
        }
        for r in rows
    ]
    return {"query": query, "count": len(results), "results": results}


# ─── 진입점 ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8419)
