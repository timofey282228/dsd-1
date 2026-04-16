import asyncio
import logging
import threading

from hazelcast.client import HazelcastClient
from hazelcast.core import HazelcastJsonValue
from hazelcast.errors import HazelcastClientNotActiveError
from hazelcast.future import Future as HzFuture
from hazelcast.proxy import Queue

from . import AddTransactionMessage
from .abstract_counter import AbstractCounter

logger = logging.getLogger(__name__)


class CounterQueueListener:
    QUEUE_NAME = "microservices.counter"

    def __init__(
        self, counter: AbstractCounter, client: HazelcastClient, queue_name=QUEUE_NAME
    ):
        logger.debug("Initializing CounterQueueListener instance...")
        super().__init__()
        self.queue: Queue[HazelcastJsonValue] = client.get_queue(queue_name)
        self.counter: AbstractCounter = counter
        self._shutdown = threading.Event()
        self._tasks = set()
        self._loop = asyncio.get_running_loop()

    def _take_callback(self, hz_future: HzFuture[HazelcastJsonValue]):
        try:
            add_transaction_message_json = hz_future.result().to_string()
            add_transaction = AddTransactionMessage.model_validate_json(
                add_transaction_message_json
            )
            execute_transaction_task = self._loop.create_task(
                self.counter.execute_transaction(
                    user_id=add_transaction.user_id,
                    transaction=add_transaction.transaction_request,
                )
            )
            self._tasks.add(execute_transaction_task)
            execute_transaction_task.add_done_callback(self._tasks.discard)
            execute_transaction_task.add_done_callback(
                self._counter_execute_transaction_callback
            )

        except HazelcastClientNotActiveError:
            if self._shutdown.is_set():
                pass  # leftover future after shutting down
            else:
                raise  # HazelcastClientNotActiveError

    def _counter_execute_transaction_callback(self, _: asyncio.Task):
        pass

    def shutdown(self):
        logger.debug("%s shutting down..", self)
        self._shutdown.set()

    def _take_while_not_shutting_down(self, _=None):
        if not self._shutdown.is_set():
            take_future = self.queue.take()
            self._tasks.add(take_future)
            take_future.add_done_callback(self._tasks.discard)
            take_future.add_done_callback(self._take_while_not_shutting_down)
            take_future.add_done_callback(self._take_callback)

    async def start(self):
        await asyncio.to_thread(self._run)

    def _run(self):
        self._take_while_not_shutting_down()
