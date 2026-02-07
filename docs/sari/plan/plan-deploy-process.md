# Sari 배포 프로세스 요약

## 목적
- 태그 기반 릴리스와 PyPI 배포의 버전 일관성을 확보한다.
- GitHub Release, PyPI, 설치 스크립트가 동일 버전을 가리키게 한다.

## 트리거
- `vX.Y.Z` 형식의 태그 푸시

## 표준 흐름
1. `release` 잡이 태그에서 버전을 추출한다.
2. `release` 잡이 `main` 브랜치에서 `sari/version.py`를 태그 버전으로 갱신하고 커밋/푸시한다.
3. GitHub Release를 태그 기준으로 생성한다.
4. `publish-pypi` 잡이 태그 커밋을 체크아웃한다.
5. PyPI 빌드 직전에 `sari/version.py`를 태그 버전으로 로컬 갱신(커밋 없음)한다.
6. `python -m build` 후 PyPI로 업로드한다.
7. 릴리스 완료 후 `horadric-forge` 업데이트 이벤트를 전송한다.

## 주의사항
- 태그 버전과 PyPI 패키지 버전이 항상 같아야 한다.
- `main` 브랜치에도 동일 버전이 반영되어야 한다.
- 설치 스크립트는 `main`을 참조하므로, `main` 버전 동기화가 필요하다.
