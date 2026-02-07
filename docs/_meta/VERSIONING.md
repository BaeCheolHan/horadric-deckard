# Versioning

## 현재 버전
- **v2.5.0** (2026-01-30)

## 버전 표기 위치 (14곳)

| # | 파일 | 확인 방법 |
|---|------|-----------|
| 1 | `README.md` | 헤더 |
| 2 | `.codex/AGENTS.md` | 헤더 |
| 3 | `.codex/system-prompt.txt` | 1행 |
| 4 | `.codex/config.toml` | 주석 |
| 5 | `.codex/quick-start.md` | 설치 명령/zip명 |
| 6 | `docs/_meta/SETUP.md` | 헤더/설치 명령 |
| 7 | `docs/_meta/SELF_REVIEW.md` | 헤더 |
| 8 | `docs/_meta/RELEASE_CHECKLIST.md` | 헤더 |
| 9 | `docs/_meta/CHANGELOG.md` | 최신 항목 |
| 10 | `docs/_meta/VERSIONING.md` | 현재 버전 |
| 11 | `install.sh` | 헤더/메시지 |
| 12 | `uninstall.sh` | 헤더 |
| 13 | `.codex/tools/local-search/mcp/server.py` | SERVER_VERSION |
| 14 | 폴더명/zip명 | codex-rules-v2.3.3-workspace-msa |

## 버전 업데이트 절차

1. 모든 14곳 버전 업데이트
2. CHANGELOG.md에 변경사항 기록
3. RELEASE_CHECKLIST.md 전수 검증
4. zip 패키징

## Semantic Versioning

- **Major** (X.0.0): 구조 변경, 호환성 파괴
- **Minor** (0.X.0): 기능 추가, 호환성 유지
- **Patch** (0.0.X): 버그 수정, 문서 수정
