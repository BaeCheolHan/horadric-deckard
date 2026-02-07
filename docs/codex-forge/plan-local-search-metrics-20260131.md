# local-search 기여도 측정 계획

> **작성일**: 2026-01-31  
> **버전**: v1.0  
> **목표**: LS가 토큰/시간/비용을 얼마나 절감했는지 정량화

---

## 배경

### 문제
- **현재**: LS 효과를 체감만 할 뿐, 수치로 증명 불가
- **필요**: "LS가 토큰 X% 절감", "턴 Y개 단축" 같은 정량적 증거

### 목표
1. **LS 기여도 측정** — 토큰/턴/시간 절감량 수치화
2. **A/B 비교** — LS ON vs OFF 실험 지원
3. **최소 구현** — 4개 핵심 지표만 로깅

---

## 핵심 지표 설계

### 최소 구현 (4개 지표)

| 지표 | 설명 | 수집 위치 |
|------|------|-----------|
| `ls.search` 호출 수 | LS 검색 사용 빈도 | MCP server |
| `snippet_chars_total` | 응답 스니펫 총 문자 수 | MCP server |
| `read_file` 호출 수 | 파일 읽기 도구 사용 | CLI/Agent |
| `read_lines_total` | 읽은 총 라인 수 | CLI/Agent |

**기여도 계산:**
```
읽기 절감율 = 1 - (read_lines_with_LS / read_lines_baseline)
토큰 추정 = snippet_chars_total / 4
```

---

### 권장 로그 필드 (확장)

#### MCP 서버 로그 (per tool call)

```json
{
  "tool": "ls.search",
  "query_hash": "a3f2e1...",
  "top_k": 10,
  "filters": {"repo": "codex-forge"},
  "results_count": 3,
  "payload_bytes": 1524,
  "snippet_chars_total": 850,
  "latency_ms": 45,
  "cache_hit": true,
  "timestamp": "2026-01-31T11:00:00Z"
}
```

#### 세션 집계 로그

```json
{
  "session_id": "uuid",
  "duration_sec": 180,
  "ls_search_count": 5,
  "ls_chars_total": 4200,
  "read_file_count": 2,
  "read_lines_total": 150,
  "total_turns": 8,
  "task_type": "refactoring"
}
```

---

## A/B 테스트 설계

### 실험 구조

**동일 작업 10개 선정:**
- 설계 5개
- 리팩토링 3개
- 버그 분석 2개

**비교 조건:**
- **Group A**: LS ON (5개 작업)
- **Group B**: LS OFF (5개 작업)

**측정 지표:**

| 지표 | 설명 |
|------|------|
| 총 토큰 (input/output) | LLM API 비용 |
| 총 턴 수 | 작업 완료까지 대화 횟수 |
| 완료 시간 (wall time) | 벽시계 기준 |
| `read_file` 라인 수 | 읽은 코드량 |
| 추가 질문 횟수 | Clarification turn |

---

### 기대 패턴

**LS ON 효과:**
```
✅ 턴 수 감소 (평균 -30%)
✅ read_file 라인 수 감소 (평균 -50%)
⚠️ input 토큰 약간 증가 (스니펫 공급)
✅ 전체 작업 시간 감소 → 총 비용 절감
```

---

## 기여도 산출 공식

### 1. 토큰 절감 기여율 (A/B 기반)
```
Savings% = (Tokens_off - Tokens_on) / Tokens_off * 100
```

### 2. 탐색 효율 기여율 (로그 기반)
```
SearchImpact = 1 - (ReadLines_on / ReadLines_baseline)
```

### 3. 시간 절감 기여율
```
TimeSavings% = (Time_off - Time_on) / Time_off * 100
```

---

## 구현 계획

### Phase 1: MCP 서버 로깅

**파일**: `src/mcp/server.py`

**추가 코드:**
```python
import logging
import json
from datetime import datetime

logger = logging.getLogger("ls-metrics")

def log_tool_call(tool, query, results, latency_ms):
    metrics = {
        "tool": tool,
        "query_hash": hashlib.md5(query.encode()).hexdigest()[:8],
        "results_count": len(results),
        "snippet_chars_total": sum(len(r['snippet']) for r in results),
        "latency_ms": latency_ms,
        "timestamp": datetime.utcnow().isoformat()
    }
    logger.info(json.dumps(metrics))
```

**로그 파일**: `{workspace}/.codex/tools/local-search/logs/metrics.jsonl`

---

### Phase 2: CLI 통합 (옵션)

**Codex CLI에서 집계:**
- `read_file` 호출 카운트
- 세션 종료 시 summary 출력

**출력 예시:**
```
📊 Session Summary:
   LS searches: 5
   Files read: 2 (150 lines)
   Estimated tokens saved: ~1050 (LS snippet 제공)
```

---

### Phase 3: A/B 비교 도구

**스크립트**: `scripts/ab_compare.py`

```python
# 두 세션 로그 비교
python3 scripts/ab_compare.py \
  --session-a logs/session_ls_on.jsonl \
  --session-b logs/session_ls_off.jsonl

# 출력:
# Tokens saved: 35%
# Turns reduced: 40%
# Time saved: 28%
```

---

## 최소 구현 체크리스트

### Phase 1: 로깅 추가
- [ ] MCP `search` tool에 로깅 추가
- [ ] 로그 필드: tool, snippet_chars_total, results_count, latency_ms
- [ ] JSONL 형식으로 저장

### Phase 2: 집계 스크립트
- [ ] `scripts/summarize_metrics.py` 작성
- [ ] 세션별 합계 계산
- [ ] 토큰 추정 (chars / 4)

### Phase 3: A/B 도구 (옵션)
- [ ] `scripts/ab_compare.py` 작성
- [ ] 두 세션 비교 리포트

---

## 예상 산출물

### 1. 로그 파일
```json
{"tool":"ls.search","snippet_chars_total":850,"results_count":3,"latency_ms":45}
{"tool":"ls.search","snippet_chars_total":620,"results_count":2,"latency_ms":32}
```

### 2. 세션 요약
```
Session: abc123
LS searches: 5
Total snippet chars: 4200 (~1050 tokens)
Files read: 2 (150 lines)
Estimated savings: 70% less reading
```

### 3. A/B 비교 리포트
```
LS ON vs OFF (5 tasks each)
Tokens: -35% (12000 → 7800)
Turns: -40% (10 → 6)
Time: -28% (5min → 3.6min)
```

---

## 통합 계획

### ai-local-search 패키지에 포함

**새 파일:**
- `src/metrics/logger.py` — 로깅 로직
- `scripts/summarize_metrics.py` — 집계
- `scripts/ab_compare.py` — A/B 비교

**설정:**
```json
{
  "metrics": {
    "enabled": true,
    "log_path": "logs/metrics.jsonl"
  }
}
```

---

## 다음 단계

1. ✅ 이 계획 승인
2. Phase 1 구현 (로깅)
3. 테스트 데이터 수집 (10개 작업)
4. A/B 실험
5. 결과 리포트

---

## 참고

- 토큰 추정: 4 chars ≈ 1 token (근사치)
- 로그 형식: JSONL (줄바꿈으로 구분된 JSON)
- A/B 실험 최소 샘플: 5개 작업 (통계적으로 유의미)
