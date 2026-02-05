from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, List, Optional, Tuple


class FsEventKind(str, Enum):
    CREATED = "CREATED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"
    MOVED = "MOVED"


@dataclass(frozen=True)
class FsEvent:
    kind: FsEventKind
    path: str
    root: str = "" # Added field
    dest_path: Optional[str] = None
    ts: float = 0.0


class TaskAction(str, Enum):
    INDEX = "INDEX"
    DELETE = "DELETE"


@dataclass
class CoalesceTask:
    action: TaskAction
    path: str
    attempts: int = 0
    enqueue_ts: float = 0.0
    last_seen: float = 0.0


@dataclass
class DbTask:
    kind: str
    rows: Optional[List[tuple]] = None
    path: Optional[str] = None
    paths: Optional[List[str]] = None
    ts: Optional[int] = None
    repo_meta: Optional[dict] = None
    engine_docs: Optional[List[dict]] = None
    engine_deletes: Optional[List[str]] = None
    snippet_rows: Optional[List[tuple]] = None
    context_rows: Optional[List[tuple]] = None
    failed_rows: Optional[List[tuple]] = None
    failed_paths: Optional[List[str]] = None
    failed_updates: Optional[List[tuple]] = None


def coalesce_action(existing: Optional[TaskAction], incoming: TaskAction) -> TaskAction:
    if incoming == TaskAction.DELETE:
        return TaskAction.DELETE
    if existing == TaskAction.DELETE:
        return TaskAction.DELETE
    return TaskAction.INDEX


def split_moved_event(event: FsEvent) -> List[Tuple[TaskAction, str]]:
    if event.kind != FsEventKind.MOVED:
        return []
    actions: List[Tuple[TaskAction, str]] = []
    if event.path:
        actions.append((TaskAction.DELETE, event.path))
    if event.dest_path:
        actions.append((TaskAction.INDEX, event.dest_path))
    return actions
