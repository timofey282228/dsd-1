from asyncio.locks import Lock
from itertools import starmap
from typing import override
from uuid import UUID

from . import Transaction, TransactionData, TransactionList, UserId
from .abstract_logging import AbstractLogging


class MemoryLogging(AbstractLogging):
    def __init__(self):
        self.lock = Lock()
        self.transactions: dict[UUID, TransactionData] = {}

    @override
    async def add_transaction(
        self,
        transaction_id: UUID,
        transaction_data: TransactionData,
    ):
        async with self.lock:
            self.transactions[transaction_id] = transaction_data

    @override
    async def get_user_transactions(self, user_id: UserId) -> TransactionList:
        async with self.lock:
            trx_shallow_copy = self.transactions.copy()

        return TransactionList(
            starmap(
                lambda transaction_id, transaction_data: Transaction(
                    transaction_id=transaction_id,
                    **transaction_data.model_dump(),
                ),
                filter(
                    lambda pair: pair[1].user_id == user_id,  # type: ignore[arg-type, index]
                    trx_shallow_copy.items(),
                ),
            )
        )
