"""Публикация заданий с подтверждением RabbitMQ."""

from typing import Protocol
from uuid import UUID

from celery import Celery
from kombu import Queue

from .store import JobStore

QUEUE_NAME = "transcription"
TASK_NAME = "orchestrator.transcribe_call"


class JobQueue(Protocol):
    def publish(self, job_id: UUID) -> None: ...


def create_celery(broker_url: str) -> Celery:
    app = Celery("transcription", broker=broker_url)
    app.conf.update(
        task_default_queue=QUEUE_NAME,
        task_queues=(Queue(QUEUE_NAME, durable=True),),
        task_default_delivery_mode="persistent",
        task_serializer="json",
        accept_content=["json"],
        task_ignore_result=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_transport_options={"confirm_publish": True},
        broker_connection_timeout=5,
        # Solo выполняет задачу в потоке брокера и не обслуживает heartbeat во время STT.
        broker_heartbeat=0,
    )
    return app


class CeleryJobQueue(JobQueue):
    def __init__(self, app: Celery) -> None:
        self.app = app

    def publish(self, job_id: UUID) -> None:
        self.app.send_task(
            TASK_NAME,
            args=[str(job_id)],
            task_id=str(job_id),
            retry=False,
            confirm_timeout=5,
        )


def publish_pending(store: JobStore, queue: JobQueue) -> None:
    for job_id in store.pending():
        queue.publish(job_id)
        store.mark_published(job_id)
