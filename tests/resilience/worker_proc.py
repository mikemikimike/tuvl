"""A worker process for the resilience tests: runs one workflow until killed.

usage: python worker_proc.py <pg_url> <project_dir> <owner>
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import yaml
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tuvl.contract.schema import WorkflowDocument
from tuvl.runtime.code import load_agents
from tuvl.runtime.queue import Worker
from tuvl.runtime.runner import Runner


async def main(pg_url: str, project: Path, owner: str) -> None:
    load_agents(project / "agents")
    doc = WorkflowDocument.model_validate(yaml.safe_load((project / "workflow.yaml").read_text()))
    engine = create_async_engine(pg_url, poolclass=NullPool)
    worker = Worker(
        engine,
        Runner(engine, {doc.metadata.name: doc}),
        owner=owner,
        lease_seconds=1.0,
        heartbeat_seconds=0.3,
        poll_seconds=0.1,
    )
    print("ready", flush=True)
    await worker.run_forever()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], Path(sys.argv[2]), sys.argv[3]))
