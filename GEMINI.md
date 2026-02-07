# Codex Rules v2.5.0 (Gemini CLI)

Gemini CLI용 진입점. **Gemini 강화 룰셋** 사용.
**v2.5.0 변경**: 버전 정합성 통일

## Rules

NOTE:
Gemini CLI는 규칙 준수 강화를 위해 `.gemini/rules/` 전용 룰셋 사용

아래 규칙들이 자동으로 로드됩니다:

@./.gemini/rules/00-core.md

**Gemini 강화 룰셋 특징:**
- 모든 핵심 정책에 CAUTION 경고 블록
- MUST 라벨 강화
- 예시 2~3배 확장
- "위반 시 작업 중단" 명시

## Quick Reference

| 명령어 | 동작 |
|--------|------|
| `/memory show` | 로드된 컨텍스트 전체 확인 |
| `/memory refresh` | 컨텍스트 파일 새로고침 |
| `/mcp` | MCP 서버 상태 확인 |
| `/help` | 도움말 |

## Sari 사용법

### MCP 도구 (권장)
Gemini CLI가 자동으로 sari MCP 도구를 로드합니다.
`/mcp` 명령으로 상태 확인.

사용 가능한 도구:
- **search**: 키워드/정규식으로 파일/코드 검색 (토큰 절감 핵심!)
- **status**: 인덱스 상태 확인
- **repo_candidates**: 관련 repo 후보 찾기

### 토큰 절감 원칙
파일 탐색 전 **반드시** sari로 먼저 검색!
- Before: 전체 탐색 → 12000 토큰
- After: sari → 900 토큰 (92% 절감)

## Scenarios

| 시나리오 | 경로 |
|----------|------|
| S0 Simple Fix | `.codex/scenarios/s0-simple-fix.md` |
| S1 Feature | `.codex/scenarios/s1-feature.md` |
| S2 Cross-repo | `.codex/scenarios/s2-cross-repo.md` |
| Hotfix | `.codex/scenarios/hotfix.md` |

## 디렉토리 구조

```
workspace/
├── .codex-root          # 마커
├── .codex/              # 룰셋/도구 (Codex 최적화)
│   ├── rules/           # Codex CLI 룰셋
│   ├── scenarios/       # 시나리오 가이드
│   ├── skills/          # 스킬
│   └── tools/           # sari 등
├── .gemini/             # Gemini CLI 전용
│   ├── rules/           # Gemini 강화 룰셋
│   └── settings.json
├── GEMINI.md            # 이 파일
├── docs/                # 공유 문서
└── [repos...]           # 실제 저장소들
```

## Codex CLI 사용자

Codex CLI를 사용하시면 `.codex/AGENTS.md`를 참조하세요.

## Navigation

- 상세 규칙: `.codex/rules/00-core.md`
- 온보딩: `.codex/quick-start.md`
- 변경 이력: `docs/_meta/CHANGELOG.md`