# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Bookbug는 출판 원고 교정용 이슈 트래커로, 웹 UI와 MCP 서버를 통해 AI 에이전트와 사람이 함께 원고를 교정할 수 있다. SQLite(WAL 모드) 기반이며 personal/team 두 가지 모드를 지원한다.

## Commands

```bash
# 의존성 설치
.venv/bin/pip install -r requirements.txt

# MCP 서버 실행 (포트 8419)
.venv/bin/python bookbug_mcp.py

# 웹 서버 실행 (포트 8420)
.venv/bin/python bookbug_web.py

# 테스트 실행
.venv/bin/python -m pytest test_bookbug_mcp.py -v

# 단일 테스트 실행
.venv/bin/python -m pytest test_bookbug_mcp.py -v -k "test_name"
```

## Architecture

Three-layer architecture with shared DB:

```
bookbug_db.py (DB layer - SQLite CRUD, import/export, user management)
    ├── bookbug_mcp.py (MCP server - 24 FastMCP tools, port 8419, Streamable HTTP)
    └── bookbug_web.py (Web UI - FastAPI + Jinja2 templates, port 8420)
```

- **bookbug_db.py**: 모든 DB 접근을 담당. `with get_db() as conn:` 패턴 사용. 스키마 자동 생성/마이그레이션 포함.
- **bookbug_mcp.py**: `@mcp.tool()` 데코레이터로 24개 도구 정의. 모든 도구는 `{ok: bool, ...}` 형태의 dict 반환 (예외를 던지지 않음).
- **bookbug_web.py**: FastAPI 라우트 + Jinja2 템플릿. LAN 기반 접근제어 (LAN=읽기/쓰기, 외부=읽기전용). 팀 모드에서는 API 키 인증 필요.
- **test_bookbug_mcp.py**: 70+ 단위 테스트. 임시 DB 사용 (프로덕션 DB 미접촉).

## DB Details

- 위치: `~/.bookbug/bookbug.db`
- 8개 테이블: projects, issues, issue_history, tags, issue_comments, issue_refs, users, project_members
- status 허용값: open, in_progress, resolved, wontfix, deferred, duplicate
- severity 허용값: critical, major, normal, minor, trivial
- issue_key는 프로젝트별 자동증가 숫자 문자열
- soft delete 패턴 (deleted_at 필드)
- issue_history에 필드 단위 변경 이력 자동 기록

## Key Conventions

- MCP 도구 응답은 항상 dict로 반환. 에러 시 `{ok: False, error: "msg"}`.
- suggestion 필드는 JSON 구조 (`{summary, items}`) 또는 레거시 평문 텍스트 모두 처리.
- heading_no = 장/절 번호 (과거 "chapter"에서 리네임됨).
- 웹 템플릿에서 `#123`, `proj#456` 형태를 자동으로 이슈 링크로 변환 (linkify_refs 필터).
