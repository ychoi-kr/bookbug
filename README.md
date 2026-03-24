# bookbug

출판 원고 교정용 이슈 트래커 MCP 서버.

Claude 에이전트가 원고를 검토하고 이슈를 등록하면, 편집자가 MCP 클라이언트를 통해 확인·처리하는 워크플로를 지원한다.

## 구성

- `bookbug_db.py` — SQLite DB 레이어 (프로젝트/이슈 CRUD, 소프트 딜리트, 임포트/익스포트)
- `bookbug_mcp.py` — FastMCP 기반 MCP 서버 (포트 8419)
- `test_bookbug_mcp.py` — 테스트 스위트

## 실행

```bash
.venv/bin/python bookbug_mcp.py
```

DB 위치: `~/.bookbug/bookbug.db`

## MCP 클라이언트 설정

### Claude Desktop (같은 기기)

`~/Library/Application Support/Claude/claude_desktop_config.json`에 추가:

```json
{
  "mcpServers": {
    "bookbug": {
      "url": "http://127.0.0.1:8419/mcp"
    }
  }
}
```

### Claude Desktop (LAN 내 다른 기기, mcp-remote 사용)

`--allow-http` 플래그가 필요하다. mcp-remote는 기본적으로 HTTP URL을 거부하기 때문.

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

`<서버_IP>`는 bookbug 서버가 실행 중인 기기의 LAN IP로 바꿀 것.

## 구현된 Tools

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
