# Call Graph Plugins

환경변수 `SARI_CALLGRAPH_PLUGIN` 으로 플러그인을 연결할 수 있습니다.

## 인터페이스

플러그인 모듈은 다음 함수를 제공할 수 있습니다.

- `augment_neighbors(direction, neighbors, context) -> neighbors`
- `filter_neighbors(direction, neighbors, context) -> neighbors`

인자:
- `direction`: `"up"` 또는 `"down"`
- `neighbors`: `list[dict]`
- `context`: `{"name": str, "path": str, "symbol_id": str}`

## 예시

```python
def augment_neighbors(direction, neighbors, context):
    # Example: add synthetic edge
    return neighbors

def filter_neighbors(direction, neighbors, context):
    # Example: remove external paths
    return [n for n in neighbors if "site-packages" not in (n.get("from_path") or n.get("to_path") or "")]
```

## 샘플 플러그인

`sari.callgraph_plugins.sample_plugin` 을 참고하세요.

## 예시: 외부 경로 제외

```python
def filter_neighbors(direction, neighbors, context):
    out = []
    for n in neighbors:
        p = n.get("from_path") or n.get("to_path") or ""
        if "site-packages" in p or "node_modules" in p:
            continue
        out.append(n)
    return out
```

## 예시: 특정 모듈 우선 처리

```python
def augment_neighbors(direction, neighbors, context):
    # 사용자 정의 룰로 이웃 리스트를 재정렬/보강 가능
    return neighbors
```
