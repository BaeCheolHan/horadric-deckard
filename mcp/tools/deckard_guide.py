#!/usr/bin/env python3
"""
Sari guidance tool for LLMs.
Returns a short usage guide to encourage search-first behavior.
"""
from typing import Any, Dict
from mcp.tools._util import mcp_response, pack_header, pack_line, pack_encode_text


def execute_deckard_guide(args: Dict[str, Any]) -> Dict[str, Any]:
    text = (
        "💡 Sari - Agentic Search Workflow Guide\n\n"
        "이 도구는 대규모 코드베이스에서 당신의 '외부 기억' 역할을 합니다. "
        "토큰을 낭비하며 파일을 하나씩 열어보기 전에, 아래 순서를 따르면 훨씬 정확하고 빠르게 임무를 완수할 수 있습니다.\n\n"
        "1. [정찰] `search` 또는 `repo_candidates`를 사용해 맥락을 파악하세요.\n"
        "2. [식별] `search_symbols`나 `search_api_endpoints`로 정확한 코드 위치를 찾으세요.\n"
        "3. [획득] `read_symbol`을 통해 필요한 구현부만 콕 집어 읽어보세요. (전체 파일을 읽는 것보다 80% 이상의 컨텍스트를 절약합니다)\n"
        "4. [분석] `get_callers` 또는 `get_implementations`로 코드 간의 연결 고리를 파악하세요.\n\n"
        "핵심 원칙: 먼저 '묻고(Search)', 필요한 것만 '취하고(Select)', 그 다음에 '행동(Act)' 하세요. "
        "이것이 당신의 추론 성능을 최상으로 유지하는 방법입니다.\n"
        "주의: 기본 모드는 경고입니다. 필요 시 search-first 모드를 warn/enforce/off로 조정할 수 있습니다."
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
