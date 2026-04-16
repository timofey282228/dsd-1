from typing import override

import httpx
import pydantic
from hazelcast.client import HazelcastClient
from hazelcast.core import HazelcastJsonValue
from hazelcast.future import Future as HzFuture
from hazelcast.proxy import Queue

from . import AllUserBalances, TransactionRequest, UserBalance, UserId
from .abstract_counter_service import AbstractCounterService
from .abstract_random_instance_generator import ServiceInstance
from .configserver_instance_generator import ConfigServerRandomInstanceGenerator


class AddTransactionMessage(pydantic.BaseModel):
    user_id: UserId
    transaction_request: TransactionRequest


class HazelcastQueueCounterService(AbstractCounterService):
    QUEUE_NAME = "microservices.counter"

    def __init__(
        self,
        hz_client: HazelcastClient,  # not the asyncio Hazelcast client, unfortunately
        instance_generator: ConfigServerRandomInstanceGenerator,
        queue_name: str = QUEUE_NAME,
    ):
        self.queue: Queue = hz_client.get_queue(queue_name)
        self.instance_generator: ConfigServerRandomInstanceGenerator = (
            instance_generator
        )

    def _add_transaction_callback(self, future: HzFuture):
        pass

    async def instance(self) -> ServiceInstance:
        return await self.instance_generator.random_instance()

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

    @override
    async def get_balance(self, user_id: UserId) -> UserBalance:
        async with (await self.instance()).refreshing_on(
            (httpx.TransportError,)
        ) as instance_address:
            host, port = instance_address
            async with httpx.AsyncClient(
                base_url=httpx.URL(
                    scheme="http",
                    host=host,
                    port=port,
                )
            ) as http_client:
                balance_response = (
                    await http_client.get(f"/users/{user_id}")
                ).raise_for_status()
        return UserBalance.model_validate_json(balance_response.read())

    @override
    async def get_all_balances(self) -> AllUserBalances:
        async with (await self.instance()).refreshing_on(
            (httpx.TransportError,)
        ) as instance_address:
            host, port = instance_address
            async with httpx.AsyncClient(
                base_url=httpx.URL(
                    scheme="http",
                    host=host,
                    port=port,
                )
            ) as http_client:
                balances_response = (
                    await http_client.get(f"/users")
                ).raise_for_status()
        return AllUserBalances.model_validate_json(balances_response.read())
