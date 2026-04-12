from typing import override

import httpx
import pydantic
from hazelcast.client import HazelcastClient
from hazelcast.core import HazelcastJsonValue
from hazelcast.future import Future as HzFuture
from hazelcast.proxy import Queue

from . import TransactionRequest, UserBalance, UserId
from .http_counter_service import HttpCounterService


class AddTransactionMessage(pydantic.BaseModel):
    user_id: UserId
    transaction_request: TransactionRequest


class HazelcastQueueCounterService(HttpCounterService):
    QUEUE_NAME = "microservices.counter"

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        hz_client: HazelcastClient,  # not the asyncio Hazelcast client, unfortunately
    ):
        super().__init__(http_client=http_client)
        self.queue: Queue = hz_client.get_queue(self.QUEUE_NAME)

    def _add_transaction_callback(self, future: HzFuture):
        pass

    @override
    async def execute_transaction(
        self,
        user_id: UserId,
        transaction: TransactionRequest,
    ) -> UserBalance:

        hz_future = self.queue.put(
            HazelcastJsonValue(
                AddTransactionMessage(
                    user_id=user_id,
                    transaction_request=transaction,
                ).model_dump_json()
            )
        )
        hz_future.add_done_callback(self._add_transaction_callback)

        return UserBalance(
            balance=-1
        )  # FIXME: there is nothing meaningful to return as balance if we request the operation via a queue, right?
