# [14] 릴리즈 0.0.2 체크리스트 v1

[scope][release][0.0.2]
**목표**: 0.0.2 릴리즈를 재현 가능하게 마감한다.

---

## A) 버전/태그
- [x] `deckard/version.py` = 0.0.2
- [x] `pyproject.toml` version 일치 확인 (dynamic attr)
- [ ] `git tag v0.0.2` 생성
- [ ] 태그는 main 최신 커밋에 위치

## B) 패키징
- [ ] `python3 -m build`
- [ ] `python3 -m twine check dist/*`
- [ ] `python3 -m twine upload dist/sari-0.0.2*`

## C) 문서
- [ ] README 설치 가이드 최신화
- [ ] 변경 로그/공지 작성 (선택)

## D) 설치/실행 smoke
- [ ] 신규 환경에서 “설정만 추가 → 자동 설치” 동작 확인
- [ ] `sari --cmd engine status` 응답 확인
- [ ] MCP search/status 기본 응답 확인

---

## 완료 기준
- PyPI 업로드 완료
- GitHub 태그/릴리즈 생성
