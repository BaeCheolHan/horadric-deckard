# [06] 검색 엔진 분리 테스트 영향 목록 v1

[tests][filters][impact]
**신규 발견**: path_pattern/exclude 변경 영향 후보 테스트 목록
**영향**: rel_path 기준 전환 시 실패/수정 가능성 있음
**다음 액션**: 영향 테스트 우선 점검

- tests/test_search_edge_cases_60.py (exclude_patterns="**/a/**")
- tests/test_cycle_1.py (exclude_patterns="node_modules/*")
- tests/test_search_100_cases.py (path_pattern="src/*", "tests/**", "**/v1/*", etc.)
- tests/test_search_filters.py (path_pattern="docs/*")
- tests/test_ranking_policy_suite.py (exclude_patterns=["doc_1"])
- tests/unit/test_mcp_tools.py (path_pattern/exclude_patterns in MCP tool)
- tests/test_integration_portability.py (path_pattern="src")
