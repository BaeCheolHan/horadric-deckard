#!/usr/bin/env python3
"""
Sari guidance tool for LLMs.
Returns a short usage guide to encourage search-first behavior.
"""
from typing import Any, Dict
from sari.mcp.tools._util import mcp_response, pack_header, pack_line, pack_encode_text


def execute_sari_guide(args: Dict[str, Any]) -> Dict[str, Any]:
    text = (
        "Sari Agentic Workflow Guide\n\n"
        "[핵심 원칙]\n"
        "- search-first: read_file 이전에 search/search_symbols/grep_and_read를 먼저 사용.\n"
        "- 최소 컨텍스트: 필요한 코드 블록만 읽고, 전체 파일 읽기는 마지막 단계에 사용.\n"
        "- 실패 폴백: search_symbols 실패 시 grep_and_read로 즉시 전환.\n\n"
        "[권장 순서]\n"
        "1) 상태 확인: status\n"
        "2) 범위 파악: repo_candidates -> list_files\n"
        "3) 위치 탐색: search / search_symbols / search_api_endpoints\n"
        "4) 코드 획득: grep_and_read / read_symbol / read_file\n"
        "5) 영향 분석: get_callers / get_implementations / call_graph\n"
        "6) 지식 저장: save_snippet / archive_context\n"
        "7) 회수/검증: get_snippet / get_context / dry_run_diff / doctor\n\n"
        "[도구 목록(공개 21 + 내부 2)]\n"
        "1. sari_guide: 사용 가이드. 불확실할 때 먼저 호출.\n"
        "2. status: 인덱스/엔진/워크스페이스 상태 확인.\n"
        "3. repo_candidates: 질의와 연관된 레포 후보 추천.\n"
        "4. list_files: 레포 구조/파일 목록 파악.\n"
        "5. search: 키워드/패턴 기반 파일 탐색.\n"
        "6. search_symbols: 심볼 단위 탐색(함수/클래스).\n"
        "7. search_api_endpoints: API 경로 기반 탐색.\n"
        "8. grep_and_read: 검색 + 상위 파일 즉시 읽기.\n"
        "9. read_symbol: 심볼 정의 블록 정밀 조회.\n"
        "10. read_file: 파일 전체 읽기(마지막 단계 권장).\n"
        "11. get_callers: 호출자(누가 부르는지) 조회.\n"
        "12. get_implementations: 구현체 조회.\n"
        "13. call_graph: 상/하위 호출 그래프 조회.\n"
        "14. call_graph_health: 콜그래프 플러그인 상태 점검.\n"
        "15. index_file: 특정 파일 강제 재인덱싱.\n"
        "16. save_snippet: 스니펫 저장.\n"
        "17. get_snippet: 저장 스니펫 조회.\n"
        "18. archive_context: 도메인 컨텍스트 저장.\n"
        "19. get_context: 저장 컨텍스트 조회.\n"
        "20. dry_run_diff: 수정 전 diff/문법 점검.\n"
        "21. doctor: 환경/DB/포트/데몬 진단.\n\n"
        "[내부 복구 도구(기본 비노출)]\n"
        "- rescan: 비동기 전체 재스캔 트리거.\n"
        "- scan_once: 동기 단발 스캔 실행.\n\n"
        "[사용 금지/주의]\n"
        "- read_file 연속 호출 금지: search 근거 없이 2회 이상 연속 호출하지 말 것.\n"
        "- 인덱스 불일치 시 즉시 doctor -> index_file 순으로 복구.\n"
        "- 대규모 분석 시 grep_and_read 우선, 필요한 파일만 read_file로 확대.\n"
        "- search_symbols에서 query는 필수이며, 필요 시 repo/kinds/path_prefix를 사용."
    )
    def build_pack() -> str:
        lines = [pack_header("sari_guide", {}, returned=1)]
        lines.append(pack_line("t", single_value=pack_encode_text(text)))
        return "\n".join(lines)

    return mcp_response(
        "sari_guide",
        build_pack,
        lambda: {"content": [{"type": "text", "text": text}]},
    )
