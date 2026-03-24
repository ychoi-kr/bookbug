# bookbug — 출판 원고 교정용 이슈 트래커 MCP 서버

## 1. 개요

출판 원고 교정 과정에서 발생하는 이슈를 프로젝트별로 관리하는 **MCP(Model Context Protocol) 서버**. LAN 상의 여러 컴퓨터에서 AI 에이전트(Claude 등)나 MCP 클라이언트가 접속하여 이슈를 등록·조회·수정할 수 있다.

### 1.1 배경

- VCS 없이 Word(.docx)와 PDF로 원고를 관리하는 출판 워크플로
- Claude 에이전트가 원고 검토 시 이슈를 발견하고, 편집자가 확인하는 흐름
- LAN 내 여러 머신에서 하나의 이슈 DB에 접근해야 함
- 기존 문제: 이슈 처리 여부 추적 불가, Claude 환각 이슈 혼재, 회차 간 연속성 없음

### 1.2 범위

**MCP 서버가 담당하는 것:**
- 프로젝트 관리 (생성, 목록, 상세)
- 이슈 CRUD + 상태 관리 + 변경 이력
- 필터링, 검색, 통계
- 태그 관리
- 일괄(batch) 처리
- 엑셀/CSV/JSON 임포트·익스포트

**MCP 서버의 범위가 아닌 것 (에이전트의 별도 스킬이 담당):**
- Word/PDF 파일에서 메모/코멘트 추출·삽입
- 파일 형식 변환, 원고 내용 비교(diff)

### 1.3 사용 시나리오

LAN 내 모든 클라이언트(Claude 에이전트, 편집자의 MCP 클라이언트 등)는 동일하게 Streamable HTTP로 서버에 접속하여 tool을 호출한다.

---

## 2. 아키텍처

```
┌────────────────────────────────────────────────────┐
│  서버 호스트                                        │
│                                                    │
│  ┌──────────────────────────────────┐              │
│  │  bookbug 서버                    │              │
│  │  (FastMCP + Streamable HTTP)     │              │
│  │                                  │              │
│  │  ┌────────────┐  ┌───────────┐  │              │
│  │  │ MCP Tools  │  │ DB Layer  │──┼──▶ ~/.bookbug/bookbug.db
│  │  │ (17 tools) │──│           │  │              │
│  │  └────────────┘  └───────────┘  │              │
│  └──────────┬───────────────────────┘              │
│             │ :8419 (HTTP)                         │
└─────────────┼──────────────────────────────────────┘
              │ LAN
    ┌─────────┴─────────┐
    │                   │
    ▼                   ▼
 Claude 에이전트      편집자 PC
```

### 2.1 기술 스택

| 구성 요소 | 선택 | 이유 |
|-----------|------|------|
| MCP 서버 프레임워크 | **FastMCP** (fastmcp 패키지) | 데코레이터 기반으로 tool 정의가 간결, streamable-http 내장 |
| 트랜스포트 | **Streamable HTTP** | LAN 원격 접속 가능, 단일 엔드포인트(/mcp), 양방향 |
| DB | **SQLite** (WAL 모드) | 설치 불필요, 단일 파일, 충분한 동시성 |
| Python | **3.10+** | FastMCP와 타입 힌트 호환 |
| 패키지 관리 | **uv** 권장 (pip도 가능) | MCP SDK 공식 권장 |

### 2.2 의존성

```
fastmcp>=2.0
pandas>=2.0        # 엑셀 임포트/익스포트용
openpyxl>=3.1      # .xlsx 읽기/쓰기
```

---

## 3. 데이터 모델

기존 CLI 버전과 동일한 SQLite 스키마를 그대로 사용한다.

### 3.1 projects

| 필드 | 타입 | 설명 |
|------|------|------|
| id | INTEGER PK | 자동 증가 |
| slug | TEXT UNIQUE | 짧은 식별자 (예: `claude-xl-ppt`) |
| title | TEXT NOT NULL | 도서명/프로젝트명 |
| description | TEXT | 프로젝트 설명 |
| base_path | TEXT | 원고 폴더 경로 (참고용) |
| created_at | TEXT | 생성 시각 |
| updated_at | TEXT | 수정 시각 |

### 3.2 issues

| 필드 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | INTEGER PK | 자동 증가 | |
| project_id | INTEGER FK | projects.id | |
| issue_key | TEXT | UNIQUE(project_id, issue_key) | 프로젝트별 키 (예: `CLAU-1`) |
| title | TEXT | NOT NULL | 이슈 제목 |
| description | TEXT | | 상세 설명 |
| status | TEXT | CHECK | `open`, `in_progress`, `resolved`, `wontfix`, `deferred` |
| category | TEXT | | 유형 (자유 텍스트, 권장값 아래 참조) |
| severity | TEXT | CHECK | `critical`, `major`, `normal`, `minor`, `trivial` |
| location | TEXT | | 파일명 + 절/페이지/단락 |
| chapter | TEXT | | 장 번호 또는 이름 |
| assignee | TEXT | | 담당자: `author`, `editor`, `claude`, `proofreader` |
| reporter | TEXT | 기본 `claude` | 보고자 |
| suggestion | TEXT | | 교정 의견 |
| resolution | TEXT | | 해결 방법 |
| source | TEXT | | 출처: `manual`, `claude`, `import` |
| created_at | TEXT | | |
| updated_at | TEXT | | |
| resolved_at | TEXT | nullable | |

#### 3.2.1 category 권장값

`맞춤법`, `띄어쓰기`, `번역투`, `사실오류`, `구조`, `스타일`, `용어`, `캡처/그림`, `데이터불일치`, `보완필요`, `파일문제`, `기타` — 자유 텍스트 허용.

### 3.3 issue_history

| 필드 | 타입 | 설명 |
|------|------|------|
| id | INTEGER PK | |
| issue_id | INTEGER FK | issues.id |
| field | TEXT | 변경된 필드명 |
| old_value | TEXT | |
| new_value | TEXT | |
| changed_by | TEXT | 변경자 |
| changed_at | TEXT | |
| note | TEXT | 변경 사유 |

### 3.4 tags

| 필드 | 타입 | 설명 |
|------|------|------|
| id | INTEGER PK | |
| issue_id | INTEGER FK | issues.id |
| tag | TEXT | UNIQUE(issue_id, tag) |

### 3.5 인덱스

```sql
CREATE INDEX idx_issues_project  ON issues(project_id);
CREATE INDEX idx_issues_status   ON issues(status);
CREATE INDEX idx_issues_chapter  ON issues(chapter);
CREATE INDEX idx_issues_category ON issues(category);
CREATE INDEX idx_history_issue   ON issue_history(issue_id);
CREATE INDEX idx_tags_issue      ON tags(issue_id);
CREATE INDEX idx_tags_tag        ON tags(tag);
```

---

## 4. MCP Tool 정의

CLI의 각 커맨드를 MCP tool로 변환한다. 모든 tool은 JSON 직렬화 가능한 dict를 반환한다.

### 4.1 프로젝트 관리 (3 tools)

#### `project_create`
프로젝트를 생성한다.

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| slug | str | ✓ | 짧은 식별자 |
| title | str | ✓ | 프로젝트 제목 |
| description | str | | 설명 |
| base_path | str | | 원고 폴더 경로 |

반환: `{"ok": true, "slug": "...", "title": "..."}`

#### `project_list`
전체 프로젝트 목록과 이슈 수 요약을 반환한다.

파라미터: 없음

반환: `{"projects": [{"slug": "...", "title": "...", "issue_count": N, "open_count": N}, ...]}`

#### `project_show`
프로젝트 상세 정보와 상태별 이슈 집계를 반환한다.

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| slug | str | ✓ | 프로젝트 식별자 |

반환: `{"slug": "...", "title": "...", "base_path": "...", "description": "...", "created_at": "...", "status_summary": {"open": N, "resolved": N, ...}}`

### 4.2 이슈 CRUD (5 tools)

#### `issue_add`
새 이슈를 등록한다. issue_key는 자동 생성.

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|----------|------|------|--------|------|
| project | str | ✓ | | 프로젝트 slug |
| title | str | ✓ | | 이슈 제목 |
| description | str | | "" | 상세 설명 |
| category | str | | "" | 유형 |
| severity | str | | "normal" | critical/major/normal/minor/trivial |
| location | str | | "" | 위치 |
| chapter | str | | "" | 장 |
| assignee | str | | "" | 담당자 |
| reporter | str | | "claude" | 보고자 |
| suggestion | str | | "" | 교정 의견 |
| source | str | | "manual" | 출처 |

반환: `{"ok": true, "issue_key": "CLAU-1", "title": "..."}`

#### `issue_list`
프로젝트의 이슈 목록을 필터링하여 반환한다.

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| project | str | ✓ | 프로젝트 slug |
| status | str | | 쉼표 구분 상태 필터 (예: "open,in_progress") |
| chapter | str | | 장 필터 |
| category | str | | 유형 필터 |
| assignee | str | | 담당자 필터 |
| severity | str | | 심각도 필터 |
| search | str | | 텍스트 검색 (title, description, suggestion) |
| sort | str | | "default" / "severity" / "updated" / "status" |

반환: `{"project": "...", "count": N, "issues": [{"issue_key": "...", "title": "...", "status": "...", "severity": "...", "category": "...", "chapter": "...", "assignee": "...", "location": "..."}, ...]}`

#### `issue_show`
이슈의 전체 상세 정보를 반환한다. 태그와 변경 이력 포함.

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| issue | str | ✓ | 이슈 키 (예: CLAU-1) 또는 ID |

반환: 이슈의 모든 필드 + `tags: [...]` + `history: [{field, old_value, new_value, changed_by, changed_at, note}, ...]`

#### `issue_update`
이슈의 필드를 수정한다. 변경 이력이 자동 기록된다. 전달된 파라미터만 수정하고 나머지는 유지.

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| issue | str | ✓ | 이슈 키 |
| title | str | | |
| description | str | | |
| status | str | | open/in_progress/resolved/wontfix/deferred |
| category | str | | |
| severity | str | | |
| location | str | | |
| chapter | str | | |
| assignee | str | | |
| suggestion | str | | |
| resolution | str | | |
| changed_by | str | | 변경자 기록 |

반환: `{"ok": true, "issue_key": "...", "updated_fields": ["status", "assignee"]}`

#### `issue_resolve`
이슈를 resolved 상태로 변경하는 단축 tool.

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| issue | str | ✓ | 이슈 키 |
| resolution | str | | 해결 방법 기록 |
| resolved_by | str | | 처리자 |

반환: `{"ok": true, "issue_key": "...", "status": "resolved"}`

### 4.3 일괄 처리 (1 tool)

#### `issue_batch_update`
여러 이슈의 상태를 한 번에 변경한다.

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| issues | str | ✓ | 이슈 키 쉼표 구분 (예: "CLAU-1,CLAU-2,CLAU-3") |
| status | str | ✓ | 변경할 상태 |
| changed_by | str | | 변경자 |

반환: `{"ok": true, "updated": 3, "skipped": ["CLAU-99"], "status": "resolved"}`

### 4.4 태그 (1 tool)

#### `issue_tag`
이슈에 태그를 추가/제거/조회한다.

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| issue | str | ✓ | 이슈 키 |
| action | str | ✓ | "add" / "remove" / "list" |
| tags | str | | 태그 쉼표 구분 (add/remove 시) |

반환: `{"issue_key": "...", "tags": ["1교", "환각", ...]}`

### 4.5 임포트/익스포트 (2 tools)

#### `import_xlsx`
엑셀 파일에서 이슈를 임포트한다.

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| project | str | ✓ | 프로젝트 slug |
| file_path | str | ✓ | 엑셀 파일의 절대 경로 |
| skip_duplicates | bool | | 기본 false |

컬럼 매핑은 아래 5.1절 참조.

반환: `{"ok": true, "imported": 35, "skipped": 2}`

#### `export_issues`
이슈를 파일로 내보낸다.

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| project | str | ✓ | 프로젝트 slug |
| output_path | str | ✓ | 출력 경로 (.xlsx / .csv / .json) |
| status | str | | 상태 필터 (선택) |

반환: `{"ok": true, "path": "...", "count": N, "format": "xlsx"}`

### 4.6 통계/이력/검색 (3 tools)

#### `project_stats`
프로젝트의 이슈 통계를 반환한다.

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| project | str | ✓ | 프로젝트 slug |

반환: `{"total": N, "by_status": {...}, "by_category": {...}, "by_chapter": {...}, "by_assignee": {...}, "by_severity": {...}}`

#### `issue_history`
특정 이슈의 변경 이력을 반환한다.

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| issue | str | ✓ | 이슈 키 |

반환: `{"issue_key": "...", "history": [{field, old_value, new_value, changed_by, changed_at, note}, ...]}`

#### `search_issues`
전체 프로젝트 또는 특정 프로젝트에서 텍스트를 검색한다.

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| query | str | ✓ | 검색어 |
| project | str | | 프로젝트 한정 (선택) |

반환: `{"query": "...", "count": N, "results": [{"project": "...", "issue_key": "...", "title": "...", ...}, ...]}`

**주의**: SQL WHERE 절에서 LIKE 조건들을 괄호로 묶을 것 (OR 우선순위 버그 방지).

```python
# 올바른 구현:
WHERE (i.title LIKE ? OR i.description LIKE ? OR i.suggestion LIKE ? ...) AND p.slug=?
# 잘못된 구현 (프로젝트 필터가 무시됨):
WHERE i.title LIKE ? OR i.description LIKE ? ... AND p.slug=?
```

---

## 5. 임포트/익스포트 상세

### 5.1 엑셀 임포트 컬럼 매핑

컬럼 헤더의 한국어/영어 변형을 유연하게 인식:

| 대상 필드 | 인식하는 컬럼명 |
|-----------|----------------|
| title | 제목, title, 이슈 |
| description | 메모 내용, 설명, description, 내용, 메모 |
| category | 유형, category, 카테고리, 분류 |
| location | 위치, 위치/맥락, location, 맥락 |
| chapter | 장, chapter, 챕터 |
| assignee | 처리 주체, 담당자, assignee, 담당 |
| reporter | 작성자, 보고자, reporter |
| suggestion | 교정 의견, suggestion, 제안, 수정 의견 |
| status | 처리상태, 상태, status |
| severity | 심각도, severity |

title 컬럼이 없으면 `[{category}] {location}` 형태로 자동 생성.

### 5.2 상태/담당자 한국어→영문 매핑

**상태:**

| 엑셀 값 | 내부 값 |
|---------|---------|
| 처리 완료, 완료 | resolved |
| 저자 확인 필요, 교정자 확인 필요 | open |
| 진행 중 | in_progress |
| 보류 | deferred |
| 무시 | wontfix |

**담당자:**

| 엑셀 값 | 내부 값 |
|---------|---------|
| 저자 확인, 저자 | author |
| 교정자 확인, 교정자 | editor |

---

## 6. issue_key 생성 규칙

- 프로젝트 slug에서 하이픈 제거 → 대문자 → 앞 4글자 = 접두어
- `{접두어}-{자동증가번호}`
- 예: slug `claude-xl-ppt` → `CLAU-1`, `CLAU-2`, ...
- DB에서 해당 접두어의 현재 최대 번호를 조회하여 +1

---

## 7. 서버 구성

### 7.1 FastMCP 서버 구조

```python
from fastmcp import FastMCP

mcp = FastMCP(
    name="bookbug",
    description="출판 원고 교정용 이슈 트래커",
    host="0.0.0.0",
    port=8419,
)

@mcp.tool()
def project_create(slug: str, title: str, description: str = "", base_path: str = "") -> dict:
    """프로젝트를 생성한다."""
    ...

@mcp.tool()
def issue_add(project: str, title: str, description: str = "", ...) -> dict:
    """새 이슈를 등록한다."""
    ...

# ... (15 tools)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

### 7.2 서버 실행

```bash
# 직접 실행
python bookbug_mcp.py

# 또는 fastmcp CLI로
fastmcp run --transport=streamable-http --host=0.0.0.0 --port=8419 bookbug_mcp.py:mcp
```

### 7.3 포트

`8419` (고정). 방화벽에서 LAN 내부만 허용.

### 7.4 DB 위치

`~/.bookbug/bookbug.db` (서버 호스트의 홈 디렉토리). 서버 시작 시 디렉토리와 테이블을 자동 생성.

---

## 8. 클라이언트 연결

클라이언트 설정 방법은 README.md 참조.

### 8.1 CLI 래퍼 (선택)

사람이 터미널에서 쓸 수 있도록, MCP tool을 호출하는 얇은 CLI 래퍼를 별도로 만들 수 있다. 이는 선택 사항이며 우선순위가 낮다.

---

## 9. 파일 구조

```
~/bookbug/
├── bookbug_mcp.py        # MCP 서버 메인 (FastMCP + 15 tools)
├── bookbug_db.py          # DB 레이어 (스키마, CRUD, 헬퍼 함수)
├── bookbug.py             # (기존) CLI 버전 — 레퍼런스용 보존
├── test_bookbug.py        # (기존) CLI 테스트
├── test_bookbug_mcp.py    # MCP 서버 테스트
├── requirements.txt        # 의존성
└── REQUIREMENTS.md         # 이 문서
```

- `bookbug_db.py`: DB 연결, 스키마 초기화, 모든 CRUD 함수를 담는다. CLI와 MCP 서버가 공유.
- `bookbug_mcp.py`: FastMCP 데코레이터로 tool을 정의하고, bookbug_db의 함수를 호출.
- 기존 `bookbug.py`의 DB/비즈니스 로직을 `bookbug_db.py`로 추출하고, `bookbug.py`(CLI)와 `bookbug_mcp.py`(MCP 서버)가 이를 공유하는 구조.

---

## 10. 테스트 요구사항

### 10.1 단위 테스트 (bookbug_db 레이어)

기존 `test_bookbug.py`의 88개 테스트를 DB 레이어 기준으로 재구성:
- 프로젝트 CRUD
- 이슈 CRUD + 키 자동 생성
- 필터링 (상태, 장, 유형, 담당자, 심각도, 텍스트 검색)
- 상태 변경 + 이력 기록
- 태그 관리
- 임포트 (컬럼 매핑, 상태 매핑, 중복 건너뛰기)
- 익스포트 (xlsx, csv, json)
- 통계 집계
- 검색 (프로젝트 필터 포함 — 괄호 버그 재발 방지)
- 프로젝트 간 데이터 격리
- CHECK 제약 조건 (잘못된 status/severity 거부)

### 10.2 MCP 서버 테스트

각 tool이 올바른 dict를 반환하는지 검증:
- tool 함수 직접 호출 테스트 (FastMCP 없이)
- 에러 케이스: 존재하지 않는 프로젝트/이슈에 대한 적절한 에러 응답

### 10.3 통합 테스트 (선택)

실제 Streamable HTTP 서버를 띄우고 MCP 클라이언트로 tool 호출:
- 프로젝트 생성 → 이슈 등록 → 조회 → 수정 → 해결 흐름

---

## 11. 에러 처리

모든 tool은 성공 시 `{"ok": true, ...}`, 실패 시 `{"ok": false, "error": "메시지"}` 형태로 반환한다.
예외를 던지지 않고 dict로 감싸서 반환하면, MCP 클라이언트(에이전트)가 에러를 자연어로 이해하고 대응할 수 있다.

| 상황 | 에러 메시지 예시 |
|------|----------------|
| 프로젝트 없음 | `"프로젝트 'xxx'를 찾을 수 없습니다"` |
| 이슈 없음 | `"이슈 'XXX-99'를 찾을 수 없습니다"` |
| slug 중복 | `"슬러그 'xxx'는 이미 존재합니다"` |
| 잘못된 status | `"유효하지 않은 상태: 'xxx'. 허용값: open, in_progress, resolved, wontfix, deferred"` |
| 파일 없음 (import) | `"파일을 찾을 수 없습니다: /path/to/file.xlsx"` |
| 업데이트할 필드 없음 | `"변경할 항목을 하나 이상 지정해 주세요"` |

---

## 12. 구현 우선순위 및 현황

- **P0 완료**: `bookbug_db.py`, `bookbug_mcp.py` (17 tools), 소프트 딜리트, 기본 테스트
- **P1 완료**: import_xlsx, export_issues, project_stats
- **P2 미구현**: CLI 래퍼, 인증, 통합 테스트
