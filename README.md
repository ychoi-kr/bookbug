# bookbug

출판 원고 교정용 이슈 트래커.

AI 에이전트나 사람이 원고를 검토하며 이슈를 등록하고, 편집자가 확인·처리하는 워크플로를 지원한다. MCP 서버와 웹 UI를 함께 제공한다.

## 주요 기능

- 프로젝트별 이슈 관리 (등록·수정·완료·삭제)
- 상태·심각도·담당자·장절 번호 기준 필터·정렬
- 이슈 변경 이력 자동 기록
- 태그, 일괄 상태 변경, 전체 텍스트 검색
- 엑셀 임포트 / xlsx·csv·json 익스포트
- 웹 UI (브라우저) + MCP 인터페이스 (AI 에이전트·클라이언트) 동시 지원

## 설치

```bash
git clone https://github.com/ychoi-kr/bookbug.git
cd bookbug
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

DB는 첫 실행 시 `~/.bookbug/bookbug.db`에 자동 생성된다.

## 실행

```bash
# 웹 UI (포트 8420)
.venv/bin/python bookbug_web.py

# MCP 서버 (포트 8419)
.venv/bin/python bookbug_mcp.py
```

macOS에서 부팅 시 자동 실행하려면 `/Library/LaunchDaemons`에 plist를 등록한다.

## 웹 UI

브라우저에서 접속:

```
http://<서버_IP>:8420
```

## MCP 클라이언트 연결

### 같은 기기

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "bookbug": {
      "url": "http://127.0.0.1:8419/mcp"
    }
  }
}
```

### LAN 내 다른 기기 (mcp-remote 사용)

```json
{
  "mcpServers": {
    "bookbug": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote@latest",
        "http://<서버_IP>:8419/mcp",
        "--allow-http"
      ]
    }
  }
}
```

`--allow-http`는 mcp-remote가 HTTP URL을 기본 차단하기 때문에 필요하다.

## MCP Tools

| Tool | 설명 |
|------|------|
| `project_create` | 프로젝트 생성 |
| `project_list` | 프로젝트 목록 |
| `project_show` | 프로젝트 상세 |
| `project_delete` | 프로젝트 소프트 딜리트 |
| `project_stats` | 프로젝트 통계 |
| `issue_add` | 이슈 등록 |
| `issue_list` | 이슈 목록 (필터/정렬) |
| `issue_show` | 이슈 상세 |
| `issue_update` | 이슈 수정 |
| `issue_resolve` | 이슈 완료 처리 |
| `issue_delete` | 이슈 소프트 딜리트 |
| `issue_batch_update` | 이슈 일괄 상태 변경 |
| `issue_tag` | 이슈 태그 추가/제거/조회 |
| `issue_history` | 이슈 변경 이력 |
| `import_xlsx` | 엑셀 임포트 |
| `export_issues` | 이슈 내보내기 (.xlsx/.csv/.json) |
| `search_issues` | 전체 텍스트 검색 |
