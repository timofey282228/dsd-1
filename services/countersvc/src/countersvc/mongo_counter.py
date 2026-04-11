from typing import override

from pymongo.asynchronous.collection import AsyncCollection, ReturnDocument

from . import Transaction, UserId
from .abstract_counter import AbstractCounter


class MongoCounter(AbstractCounter):
    def __init__(self, collection: AsyncCollection):
        self.collection: AsyncCollection = collection

    @override
    async def execute_transaction(
        self,
        user_id: UserId,
        transaction: Transaction,
    ) -> int:
        update_result = await self.collection.find_one_and_update(
            {"_id": user_id},
            {"$inc": {"amount": transaction.amount}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return update_result.get("amount", 0)

    @override
    async def get_balance(self, user_id: UserId) -> int:
        user_document = await self.collection.find_one(
            {"_id": user_id},
        )
        return user_document.get("amount", 0) if user_document is not None else 0

    @override
    async def get_balances(self) -> dict[UserId, int]:
        return {
            counter_document["_id"]: counter_document.get("amount", 0)
            async for counter_document in self.collection.find()
        }
