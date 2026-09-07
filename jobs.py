"""Bounded, owner-scoped jobs for ONE process. Not durable or distributed."""
import asyncio
from collections import deque
from dataclasses import dataclass, field
import time
import uuid


class CapacityExceeded(Exception):
    pass


@dataclass
class Job:
    owner: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "running"
    events: deque = field(default_factory=lambda: deque(maxlen=200))
    sequence: int = 0
    finished_at: float | None = None

    async def put(self, message):
        # Queue-compatible sink: bounded, nonblocking, never drained by readers.
        if message is not None:
            self.sequence += 1
            event = dict(message)
            event["message"] = str(event.get("message", ""))[:2000]
            self.events.append({**event, "sequence": self.sequence})

    def snapshot(self, after=0):
        return {"job_id": self.id, "status": self.status,
                "events": [event for event in self.events if event["sequence"] > after],
                "sequence": self.sequence}


class JobManager:
    def __init__(self, limit=1):
        self.limit = max(1, limit)
        self.jobs = {}
        self.tasks = set()
        self.active = 0

    def prune(self):
        now = time.monotonic()
        for jid, job in list(self.jobs.items()):
            if job.finished_at is not None and now - job.finished_at > 3600:
                del self.jobs[jid]
        completed = [job for job in self.jobs.values() if job.finished_at is not None]
        for job in sorted(completed, key=lambda job: job.finished_at)[:-99]:
            del self.jobs[job.id]

    def get(self, jid, owner):
        self.prune()
        job = self.jobs.get(jid)
        return job if job is not None and job.owner == owner else None

    def start(self, owner, run):
        # No await between capacity check and reservation: atomic on the app loop.
        self.prune()
        if self.active >= self.limit:
            raise CapacityExceeded
        self.active += 1
        job = Job(owner)
        self.jobs[job.id] = job

        async def execute():
            try:
                await run(job)
                job.status = "failed" if any(e.get("type") == "error" for e in job.events) else "completed"
            except asyncio.CancelledError:
                job.status = "interrupted"
                raise
            except Exception:
                job.status = "failed"
                await job.put({"type": "error", "message": "Job failed. Review server configuration and retry."})
            finally:
                job.finished_at = time.monotonic()
                self.active -= 1

        task = asyncio.create_task(execute())
        self.tasks.add(task)
        def task_finished(done):
            self.tasks.discard(done)
            # Cancellation can happen before execute() enters its try/finally.
            if job.finished_at is None:
                job.status = "interrupted"
                job.finished_at = time.monotonic()
                self.active -= 1
        task.add_done_callback(task_finished)
        return job

    async def shutdown(self):
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
