"""test_bookbug_mcp — MCP tool 함수 직접 호출 테스트

bookbug_mcp의 tool 함수를 FastMCP 없이 직접 테스트.
임시 DB를 사용하므로 실제 ~/.bookbug/bookbug.db에 영향 없음.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

# ── 임시 DB로 교체 (get_db()가 호출 시점에 DB_PATH를 참조하므로 이것으로 충분) ──
import bookbug_db
_TMP_DIR = tempfile.mkdtemp()
bookbug_db.DB_PATH = Path(_TMP_DIR) / "test_bookbug.db"

import bookbug_mcp as mcp


def fresh_db():
    """각 테스트 전 DB 파일 삭제 → 다음 get_db() 호출 시 새로 생성됨."""
    if bookbug_db.DB_PATH.exists():
        bookbug_db.DB_PATH.unlink()


class TestProjectTools(unittest.TestCase):

    def setUp(self):
        fresh_db()

    def test_project_create_ok(self):
        r = mcp.project_create("test-proj", "테스트 프로젝트")
        self.assertTrue(r["ok"])
        self.assertEqual(r["slug"], "test-proj")

    def test_project_create_duplicate_slug(self):
        mcp.project_create("dup", "첫 번째")
        r = mcp.project_create("dup", "두 번째")
        self.assertFalse(r["ok"])
        self.assertIn("이미 존재", r["error"])

    def test_project_list_empty(self):
        r = mcp.project_list()
        self.assertEqual(r["projects"], [])

    def test_project_list_with_data(self):
        mcp.project_create("p1", "프로젝트1")
        mcp.project_create("p2", "프로젝트2")
        slugs = [p["slug"] for p in mcp.project_list()["projects"]]
        self.assertIn("p1", slugs)
        self.assertIn("p2", slugs)

    def test_project_show_ok(self):
        mcp.project_create("show-test", "쇼 테스트", description="설명", base_path="/tmp")
        r = mcp.project_show("show-test")
        self.assertEqual(r["slug"], "show-test")
        self.assertEqual(r["description"], "설명")
        self.assertIn("status_summary", r)

    def test_project_show_not_found(self):
        r = mcp.project_show("nonexistent")
        self.assertFalse(r["ok"])
        self.assertIn("찾을 수 없습니다", r["error"])


class TestIssueTools(unittest.TestCase):

    def setUp(self):
        fresh_db()
        mcp.project_create("test-book", "테스트 도서")

    def test_issue_add_basic(self):
        r = mcp.issue_add("test-book", "첫 번째 이슈")
        self.assertTrue(r["ok"])
        self.assertEqual(r["issue_key"], "1")

    def test_issue_add_key_sequence(self):
        keys = [mcp.issue_add("test-book", f"이슈 {i}")["issue_key"] for i in range(3)]
        self.assertEqual(keys, ["1", "2", "3"])

    def test_issue_add_project_not_found(self):
        r = mcp.issue_add("no-project", "이슈")
        self.assertFalse(r["ok"])

    def test_issue_add_invalid_severity(self):
        r = mcp.issue_add("test-book", "이슈", severity="extreme")
        self.assertFalse(r["ok"])
        self.assertIn("심각도", r["error"])

    def test_issue_add_all_fields(self):
        r = mcp.issue_add(
            "test-book", "전체 필드 이슈",
            description="상세 설명", category="맞춤법", severity="major",
            location="1장 3절", heading_no="1", assignee="editor",
            reporter="claude", suggestion="수정 제안", source="claude",
        )
        self.assertTrue(r["ok"])
        detail = mcp.issue_show(r["issue_key"])
        self.assertEqual(detail["category"], "맞춤법")
        self.assertEqual(detail["severity"], "major")
        self.assertEqual(detail["heading_no"], "1")

    def test_issue_list_all(self):
        mcp.issue_add("test-book", "이슈 A")
        mcp.issue_add("test-book", "이슈 B")
        r = mcp.issue_list("test-book")
        self.assertEqual(r["count"], 2)

    def test_issue_list_status_filter(self):
        mcp.issue_add("test-book", "오픈 이슈")
        k2 = mcp.issue_add("test-book", "해결 이슈")["issue_key"]
        mcp.issue_resolve(k2)
        r = mcp.issue_list("test-book", status="open")
        self.assertEqual(r["count"], 1)

    def test_issue_list_heading_no_filter(self):
        mcp.issue_add("test-book", "1장 이슈", heading_no="1")
        mcp.issue_add("test-book", "2장 이슈", heading_no="2")
        r = mcp.issue_list("test-book", heading_no="1")
        self.assertEqual(r["count"], 1)

    def test_issue_list_search(self):
        mcp.issue_add("test-book", "맞춤법 오류 발견")
        mcp.issue_add("test-book", "번역투 문제")
        r = mcp.issue_list("test-book", search="맞춤법")
        self.assertEqual(r["count"], 1)

    def test_issue_show_ok(self):
        r = mcp.issue_add("test-book", "쇼 테스트")
        detail = mcp.issue_show(r["issue_key"])
        self.assertEqual(detail["issue_key"], "1")
        self.assertIn("tags", detail)
        self.assertIn("history", detail)

    def test_issue_show_not_found(self):
        from fastmcp.exceptions import ToolError
        with self.assertRaises(ToolError):
            mcp.issue_show("9999")

    def test_issue_update_status(self):
        k = mcp.issue_add("test-book", "업데이트 테스트")["issue_key"]
        upd = mcp.issue_update(k, status="in_progress", changed_by="editor")
        self.assertTrue(upd["ok"])
        self.assertIn("status", upd["updated_fields"])
        self.assertEqual(mcp.issue_show(k)["status"], "in_progress")

    def test_issue_update_records_history(self):
        k = mcp.issue_add("test-book", "이력 테스트")["issue_key"]
        mcp.issue_update(k, status="resolved", changed_by="tester")
        detail = mcp.issue_show(k)
        self.assertTrue(len(detail["history"]) > 0)
        self.assertEqual(detail["history"][0]["changed_by"], "tester")

    def test_issue_update_no_fields(self):
        k = mcp.issue_add("test-book", "빈 업데이트")["issue_key"]
        r = mcp.issue_update(k)
        self.assertFalse(r["ok"])

    def test_issue_update_invalid_status(self):
        k = mcp.issue_add("test-book", "잘못된 상태")["issue_key"]
        r = mcp.issue_update(k, status="invalid")
        self.assertFalse(r["ok"])

    def test_issue_update_not_found(self):
        from fastmcp.exceptions import ToolError
        with self.assertRaises(ToolError):
            mcp.issue_update("9999", status="resolved")

    def test_issue_resolve(self):
        k = mcp.issue_add("test-book", "해결 테스트")["issue_key"]
        res = mcp.issue_resolve(k, resolution="수정 완료", resolved_by="editor")
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "resolved")
        detail = mcp.issue_show(k)
        self.assertEqual(detail["status"], "resolved")
        self.assertEqual(detail["resolution"], "수정 완료")
        self.assertIsNotNone(detail["resolved_at"])

    def test_issue_resolve_not_found(self):
        from fastmcp.exceptions import ToolError
        with self.assertRaises(ToolError):
            mcp.issue_resolve("9999")


class TestIssueProjectScoping(unittest.TestCase):

    def setUp(self):
        fresh_db()
        mcp.project_create("proj-a", "프로젝트 A")
        mcp.project_create("proj-b", "프로젝트 B")
        mcp.issue_add("proj-a", "A 이슈 1")
        mcp.issue_add("proj-b", "B 이슈 1")

    def test_issue_show_ambiguous_without_project(self):
        from fastmcp.exceptions import ToolError
        with self.assertRaises(ToolError) as ctx:
            mcp.issue_show("1")
        self.assertIn("여러 프로젝트", str(ctx.exception))

    def test_issue_show_with_project(self):
        r = mcp.issue_show("1", project="proj-b")
        self.assertEqual(r["title"], "B 이슈 1")

    def test_issue_update_with_project(self):
        r = mcp.issue_update("1", project="proj-b", status="in_progress")
        self.assertTrue(r["ok"])
        self.assertEqual(mcp.issue_show("1", project="proj-b")["status"], "in_progress")
        self.assertEqual(mcp.issue_show("1", project="proj-a")["status"], "open")

    def test_issue_resolve_with_project(self):
        r = mcp.issue_resolve("1", project="proj-a", resolution="A만 해결")
        self.assertTrue(r["ok"])
        self.assertEqual(mcp.issue_show("1", project="proj-a")["status"], "resolved")
        self.assertEqual(mcp.issue_show("1", project="proj-b")["status"], "open")

    def test_slug_key_format_still_supported(self):
        r = mcp.issue_show("proj-a#1")
        self.assertEqual(r["title"], "A 이슈 1")


class TestBatchUpdate(unittest.TestCase):

    def setUp(self):
        fresh_db()
        mcp.project_create("batch-proj", "배치 프로젝트")
        self.k1 = mcp.issue_add("batch-proj", "이슈 1")["issue_key"]
        self.k2 = mcp.issue_add("batch-proj", "이슈 2")["issue_key"]
        self.k3 = mcp.issue_add("batch-proj", "이슈 3")["issue_key"]

    def test_batch_update_all(self):
        r = mcp.issue_batch_update(f"{self.k1},{self.k2},{self.k3}", "resolved")
        self.assertTrue(r["ok"])
        self.assertEqual(r["updated"], 3)
        self.assertEqual(r["skipped"], [])

    def test_batch_update_partial_missing(self):
        r = mcp.issue_batch_update(f"{self.k1},9999,{self.k2}", "in_progress")
        self.assertTrue(r["ok"])
        self.assertEqual(r["updated"], 2)
        self.assertIn("9999", r["skipped"])

    def test_batch_update_invalid_status(self):
        r = mcp.issue_batch_update(self.k1, "bad_status")
        self.assertFalse(r["ok"])


class TestTagTools(unittest.TestCase):

    def setUp(self):
        fresh_db()
        mcp.project_create("tag-proj", "태그 프로젝트")
        self.key = mcp.issue_add("tag-proj", "태그 테스트")["issue_key"]

    def test_tag_add(self):
        r = mcp.issue_tag(self.key, "add", "1교,환각")
        self.assertEqual(set(r["tags"]), {"1교", "환각"})

    def test_tag_list(self):
        mcp.issue_tag(self.key, "add", "검토필요")
        r = mcp.issue_tag(self.key, "list")
        self.assertIn("검토필요", r["tags"])

    def test_tag_remove(self):
        mcp.issue_tag(self.key, "add", "a,b,c")
        mcp.issue_tag(self.key, "remove", "b")
        r = mcp.issue_tag(self.key, "list")
        self.assertNotIn("b", r["tags"])
        self.assertIn("a", r["tags"])

    def test_tag_add_duplicate_idempotent(self):
        mcp.issue_tag(self.key, "add", "dup")
        mcp.issue_tag(self.key, "add", "dup")
        r = mcp.issue_tag(self.key, "list")
        self.assertEqual(r["tags"].count("dup"), 1)

    def test_tag_issue_not_found(self):
        r = mcp.issue_tag("9999", "list")
        self.assertFalse(r["ok"])

    def test_tag_invalid_action(self):
        r = mcp.issue_tag(self.key, "badaction")
        self.assertFalse(r["ok"])


class TestStatsAndHistory(unittest.TestCase):

    def setUp(self):
        fresh_db()
        mcp.project_create("stats-proj", "통계 프로젝트")
        k1 = mcp.issue_add("stats-proj", "이슈 1", category="맞춤법", severity="major", heading_no="1")["issue_key"]
        mcp.issue_add("stats-proj", "이슈 2", category="번역투", severity="normal", heading_no="1")
        mcp.issue_add("stats-proj", "이슈 3", category="맞춤법", severity="minor", heading_no="2")
        mcp.issue_resolve(k1)

    def test_project_stats(self):
        r = mcp.project_stats("stats-proj")
        self.assertEqual(r["total"], 3)
        self.assertEqual(r["by_status"].get("resolved", 0), 1)
        self.assertEqual(r["by_category"].get("맞춤법", 0), 2)

    def test_project_stats_not_found(self):
        r = mcp.project_stats("no-proj")
        self.assertFalse(r["ok"])

    def test_issue_history_tool(self):
        k = mcp.issue_add("stats-proj", "이력 이슈")["issue_key"]
        mcp.issue_update(k, status="in_progress", changed_by="tester")
        mcp.issue_resolve(k, resolved_by="editor")
        r = mcp.issue_history(k)
        self.assertEqual(r["issue_key"], k)
        self.assertGreaterEqual(len(r["history"]), 2)

    def test_issue_history_not_found(self):
        from fastmcp.exceptions import ToolError
        with self.assertRaises(ToolError):
            mcp.issue_history("9999")


class TestSearchIssues(unittest.TestCase):

    def setUp(self):
        fresh_db()
        mcp.project_create("search-a", "검색 프로젝트 A")
        mcp.project_create("search-b", "검색 프로젝트 B")
        mcp.issue_add("search-a", "파이썬 타입 힌트 오류")
        mcp.issue_add("search-a", "번역투 문장")
        mcp.issue_add("search-b", "파이썬 import 누락", suggestion="import 추가 필요")

    def test_search_all_projects(self):
        r = mcp.search_issues("파이썬")
        self.assertEqual(r["count"], 2)

    def test_search_with_project_filter(self):
        """프로젝트 필터가 올바르게 AND 처리되는지 확인 (SQL OR 우선순위 버그 방지)"""
        r = mcp.search_issues("파이썬", project="search-a")
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["results"][0]["project"], "search-a")

    def test_search_no_results(self):
        r = mcp.search_issues("존재하지않는검색어xyz")
        self.assertEqual(r["count"], 0)

    def test_search_project_isolation(self):
        r = mcp.search_issues("번역투", project="search-b")
        self.assertEqual(r["count"], 0)

    def test_search_suggestion_field(self):
        r = mcp.search_issues("import 추가")
        self.assertEqual(r["count"], 1)


class TestImportExport(unittest.TestCase):

    def setUp(self):
        fresh_db()
        mcp.project_create("imp-proj", "임포트 프로젝트")
        self.tmp_dir = tempfile.mkdtemp()

    def test_export_json(self):
        mcp.issue_add("imp-proj", "이슈 1", heading_no="1", category="맞춤법")
        mcp.issue_add("imp-proj", "이슈 2", heading_no="2", category="번역투")
        out = os.path.join(self.tmp_dir, "out.json")
        r = mcp.export_issues("imp-proj", out)
        self.assertTrue(r["ok"])
        self.assertEqual(r["count"], 2)
        self.assertEqual(r["format"], "json")
        with open(out, encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)), 2)

    def test_export_csv(self):
        mcp.issue_add("imp-proj", "CSV 이슈")
        out = os.path.join(self.tmp_dir, "out.csv")
        r = mcp.export_issues("imp-proj", out)
        self.assertTrue(r["ok"])
        self.assertEqual(r["format"], "csv")

    def test_export_status_filter(self):
        mcp.issue_add("imp-proj", "오픈 이슈")
        k2 = mcp.issue_add("imp-proj", "해결 이슈")["issue_key"]
        mcp.issue_resolve(k2)
        out = os.path.join(self.tmp_dir, "open_only.json")
        r = mcp.export_issues("imp-proj", out, status="open")
        self.assertTrue(r["ok"])
        self.assertEqual(r["count"], 1)

    def test_export_project_not_found(self):
        r = mcp.export_issues("no-proj", "/tmp/x.json")
        self.assertFalse(r["ok"])

    def test_import_file_not_found(self):
        r = mcp.import_xlsx("imp-proj", "/nonexistent/file.xlsx")
        self.assertFalse(r["ok"])
        self.assertIn("찾을 수 없습니다", r["error"])

    def test_import_project_not_found(self):
        r = mcp.import_xlsx("no-proj", "/tmp/x.xlsx")
        self.assertFalse(r["ok"])

    def test_import_xlsx_and_verify(self):
        try:
            import pandas as pd
        except ImportError:
            self.skipTest("pandas not installed")

        data = {
            "장": ["1", "2", "3"],
            "위치/맥락": ["1.1절", "2.3절", "3.1절"],
            "유형": ["맞춤법", "번역투", "구조"],
            "메모 내용": ["첫 번째 메모", "두 번째 메모", "세 번째 메모"],
            "작성자": ["Claude", "Claude", "Claude"],
            "처리 주체": ["저자", "교정자", "저자"],
            "교정 의견": ["제안1", "제안2", "제안3"],
            "처리상태": ["저자 확인 필요", "처리 완료", "교정자 확인 필요"],
        }
        xls_path = os.path.join(self.tmp_dir, "test_import.xlsx")
        pd.DataFrame(data).to_excel(xls_path, index=False)

        r = mcp.import_xlsx("imp-proj", xls_path)
        self.assertTrue(r["ok"])
        self.assertEqual(r["imported"], 3)

        listed = mcp.issue_list("imp-proj")
        self.assertEqual(listed["count"], 3)
        statuses = [i["status"] for i in listed["issues"]]
        self.assertIn("open", statuses)
        self.assertIn("resolved", statuses)

    def test_import_skip_duplicates(self):
        try:
            import pandas as pd
        except ImportError:
            self.skipTest("pandas not installed")

        data = {"메모 내용": ["중복 메모"], "위치/맥락": ["1.1절"], "유형": ["맞춤법"]}
        xls_path = os.path.join(self.tmp_dir, "dup_test.xlsx")
        pd.DataFrame(data).to_excel(xls_path, index=False)

        mcp.import_xlsx("imp-proj", xls_path)
        r2 = mcp.import_xlsx("imp-proj", xls_path, skip_duplicates=True)
        self.assertTrue(r2["ok"])
        self.assertEqual(r2["skipped"], 1)
        self.assertEqual(r2["imported"], 0)


class TestProjectIsolation(unittest.TestCase):

    def setUp(self):
        fresh_db()
        mcp.project_create("proj-a", "프로젝트 A")
        mcp.project_create("proj-b", "프로젝트 B")

    def test_issue_list_only_returns_own_project(self):
        mcp.issue_add("proj-a", "A 전용 이슈")
        mcp.issue_add("proj-b", "B 전용 이슈")
        self.assertEqual(mcp.issue_list("proj-a")["count"], 1)
        self.assertEqual(mcp.issue_list("proj-b")["count"], 1)

    def test_stats_isolated(self):
        mcp.issue_add("proj-a", "A 이슈")
        mcp.issue_add("proj-a", "A 이슈 2")
        mcp.issue_add("proj-b", "B 이슈")
        self.assertEqual(mcp.project_stats("proj-a")["total"], 2)
        self.assertEqual(mcp.project_stats("proj-b")["total"], 1)


class TestIssueKeyGeneration(unittest.TestCase):

    def setUp(self):
        fresh_db()

    def test_key_is_integer_string(self):
        mcp.project_create("claude-xl-ppt", "Claude XL PPT")
        r = mcp.issue_add("claude-xl-ppt", "이슈")
        self.assertEqual(r["issue_key"], "1")

    def test_key_sequential(self):
        mcp.project_create("seq-test", "순번 테스트")
        keys = [mcp.issue_add("seq-test", f"이슈 {i}")["issue_key"] for i in range(5)]
        self.assertEqual(keys, ["1", "2", "3", "4", "5"])

    def test_keys_independent_per_project(self):
        mcp.project_create("proj-a", "A")
        mcp.project_create("proj-b", "B")
        a1 = mcp.issue_add("proj-a", "A 이슈")["issue_key"]
        b1 = mcp.issue_add("proj-b", "B 이슈")["issue_key"]
        a2 = mcp.issue_add("proj-a", "A 이슈 2")["issue_key"]
        self.assertEqual(a1, "1")
        self.assertEqual(b1, "1")
        self.assertEqual(a2, "2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
