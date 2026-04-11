from itertools import starmap
from typing import Annotated, override
from uuid import UUID

from hazelcast.asyncio import HazelcastClient, Map
from hazelcast.core import HazelcastJsonValue
from hazelcast.predicate import equal

from . import Transaction, TransactionData, TransactionList
from .abstract_logging import AbstractLogging


class HazelcastLogging(AbstractLogging):
    def __init__(self, _map: Map):
        self._map: Map[UUID, Annotated[HazelcastJsonValue, TransactionData]] = _map

    @classmethod
    async def from_hz_client(cls, hz: HazelcastClient):
        return cls(_map=await hz.get_map("logs"))

    @override
    async def add_transaction(self, transaction_id, transaction_data):
        await self._map.put(
            transaction_id, HazelcastJsonValue(transaction_data.model_dump_json())
        )

    @override
    async def get_user_transactions(self, user_id):
        transactions_json = await self._map.entry_set(equal("user_id", user_id))
        return TransactionList(
            starmap(
                lambda transaction_id, transaction_data_dict: Transaction(
                    transaction_id=transaction_id,
                    **transaction_data_dict.loads(),
                ),
                transactions_json,
            )
        )
