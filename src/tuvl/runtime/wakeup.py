"""In-process wakeups for run event streams.

A reader (the SSE endpoint) ``listen``\\ s on a run; whatever commits a journal event or a draft
piece for that run calls ``notify`` and the reader queries at once instead of waiting for its next
poll. Only readers in the same process are woken: writes from another worker process are picked up
by the reader's fallback poll.

Journal events are written inside a caller's transaction, so :func:`mark` records the run on the
session and :func:`notify` runs from the session's ``after_commit`` hook. Waking before the commit
would let a reader query and see nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Iterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

_INFO_KEY = "tuvl_wake_runs"
_listeners: dict[uuid.UUID, set[tuple[asyncio.AbstractEventLoop, asyncio.Event]]] = {}


@contextlib.contextmanager
def listen(run_id: uuid.UUID) -> Iterator[asyncio.Event]:
    """An event set whenever something for *run_id* is committed in this process."""
    entry = (asyncio.get_running_loop(), asyncio.Event())
    _listeners.setdefault(run_id, set()).add(entry)
    try:
        yield entry[1]
    finally:
        waiting = _listeners.get(run_id)
        if waiting is not None:
            waiting.discard(entry)
            if not waiting:
                del _listeners[run_id]


def notify(run_id: uuid.UUID) -> None:
    for loop, ev in tuple(_listeners.get(run_id, ())):
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            ev.set()
        elif not loop.is_closed():
            loop.call_soon_threadsafe(ev.set)


def mark(session: AsyncSession | Session, run_id: uuid.UUID) -> None:
    """Notify *run_id*'s listeners once *session*'s transaction commits."""
    sync = session.sync_session if isinstance(session, AsyncSession) else session
    sync.info.setdefault(_INFO_KEY, set()).add(run_id)


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    runs: Any = session.info.pop(_INFO_KEY, None)
    for run_id in runs or ():
        notify(run_id)


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop(_INFO_KEY, None)
