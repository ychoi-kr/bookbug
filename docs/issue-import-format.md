# bookbug 이슈 일괄 import JSON 포맷

> 최종 업데이트: 2026-04-21

bookbug에 연결되지 않은 환경에서 이슈를 작성한 뒤, JSON 파일로 저장하여 일괄 import할 수 있다.

## 파일 구조

```json
{
  "project": "<프로젝트 slug>",
  "reporter": "<작성자>",
  "issues": [
    { ... },
    { ... }
  ]
}
```

- `project` — import 대상 프로젝트의 slug (예: `"cs-interview"`)
- `reporter` — 모든 이슈에 공통 적용되는 작성자 (기본값: `"claude"`)
- `issues` — 이슈 객체 배열

## 이슈 객체 필드

| 필드 | 필수 | 기본값 | 설명 |
|------|:----:|--------|------|
| `title` | O | | 이슈 제목 |
| `description` | | `""` | 문제 상세 설명 (순수 텍스트) |
| `severity` | | `"normal"` | 심각도: `critical` / `major` / `normal` / `minor` / `trivial` |
| `heading_no` | | `""` | 장절 번호 (예: `"2.3"`, `"1.1.5"`) |
| `location` | | `""` | 원고 내 위치 (예: `"코드 1.2 캡션"`, `"p.42 3번째 문단"`) |
| `category` | | `""` | 분류 태그 |
| `suggestion` | | `""` | 교정 의견. 문자열 또는 `{summary, items}` 객체 |
| `manuscript` | | `""` | 원고 파일명 또는 URL (예: `"CS면접_1부_1교.docx"`) |

- `issue_key`는 import 시 자동 부여되므로 포함하지 않는다.
- 빈 문자열(`""`)이 기본값인 필드는 생략 가능하다.

## suggestion 필드

문자열 또는 JSON 객체 두 가지 형태를 지원한다.

### 평문 텍스트

```json
"suggestion": "캡션을 '합계 계산 함수'로 수정"
```

### 구조화된 교정 의견 (권장)

```json
"suggestion": {
  "summary": "교정 의견 요약",
  "items": [
    {
      "before_desc": "수정 대상 위치 설명",
      "before": "현재 텍스트",
      "after_desc": "수정 이유",
      "after": "수정 후 텍스트"
    }
  ]
}
```

- `items`가 여러 개일 수 있다.
- import 시 객체는 자동으로 JSON 문자열로 변환된다.

## 샘플 파일

```json
{
  "project": "cs-interview",
  "reporter": "claude",
  "issues": [
    {
      "title": "2.3 스택 — 코드 캡션 오류",
      "description": "코드 1.2 캡션이 '배열 생성'으로 되어 있으나 실제 내용은 sum() 함수이다.",
      "severity": "normal",
      "heading_no": "2.3",
      "location": "코드 1.2 캡션",
      "suggestion": {
        "summary": "캡션을 '합계 계산 함수'로 수정",
        "items": [
          {
            "before_desc": "코드 1.2 캡션",
            "before": "배열 생성",
            "after_desc": "실제 코드 내용에 맞게 수정",
            "after": "합계 계산 함수"
          }
        ]
      }
    },
    {
      "title": "5.3 동적 계획법 — 소제목 용어 불일치",
      "description": "소제목에 '탑다운과 바텀업'이 남아 있으나 본문은 '하향식/상향식'으로 통일되어 있다.",
      "severity": "minor",
      "heading_no": "5.3",
      "location": "소제목"
    },
    {
      "title": "3.1 연결 리스트 — 그림 번호 누락",
      "description": "그림 3.2가 본문에서 참조되지만 실제 그림 캡션은 3.1로 되어 있다.",
      "severity": "major",
      "heading_no": "3.1",
      "location": "그림 3.2",
      "suggestion": "그림 캡션 번호를 3.2로 수정하거나 본문 참조를 3.1로 통일",
      "manuscript": "CS면접_2부_1교_20260401.docx"
    }
  ]
}
```

## import 방법

bookbug가 설치된 머신에서 다음과 같이 실행한다.

```bash
cd ~/bookbug
.venv/bin/python scripts/import_issues.py issues.json
```

또는 Python에서 직접:

```python
import json, sqlite3, sys
sys.path.insert(0, '/home/yong/bookbug')  # 또는 ~/bookbug
from bookbug_db import db_issue_add

conn = sqlite3.connect('/home/yong/.bookbug/bookbug.db')

with open('issues.json', encoding='utf-8') as f:
    data = json.load(f)

proj_id = conn.execute(
    "SELECT id FROM projects WHERE slug=?", (data['project'],)
).fetchone()[0]

for iss in data['issues']:
    suggestion = iss.get('suggestion', '')
    if isinstance(suggestion, dict):
        suggestion = json.dumps(suggestion, ensure_ascii=False)

    result = db_issue_add(
        conn, proj_id,
        title=iss['title'],
        description=iss.get('description', ''),
        category=iss.get('category', ''),
        severity=iss.get('severity', 'normal'),
        location=iss.get('location', ''),
        heading_no=iss.get('heading_no', ''),
        reporter=data.get('reporter', 'claude'),
        suggestion=suggestion,
        manuscript=iss.get('manuscript', ''),
    )
    print(f"[{result['issue_key']}] {result['title']}")
```

## 주의사항

- `severity`에 허용되지 않는 값을 넣으면 `ValueError`가 발생한다.
- `description`과 `suggestion`에 XML/HTML 태그(`<parameter>`, `</invoke>` 등)가 포함되면 MCP 경유 시 마크업 누수 검증에 걸린다. 순수 텍스트만 입력할 것.
- 같은 파일을 두 번 import하면 이슈가 중복 생성된다. `issue_key`가 자동 증가하므로 되돌리려면 hard delete가 필요하다.
