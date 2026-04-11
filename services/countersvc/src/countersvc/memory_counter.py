from asyncio.locks import Lock

from . import Transaction, UserBalance, UserId
from .abstract_counter import AbstractCounter


class MemoryCounter(AbstractCounter):
    def __init__(self):
        self.lock = Lock()
        self.balances: dict = {}

    async def execute_transaction(
        self,
        user_id: UserId,
        transaction: Transaction,
    ) -> int:
        async with self.lock:
            if user_id in self.balances:
                new_balance = self.balances[user_id] + transaction.amount
            else:
                new_balance = transaction.amount
            self.balances[user_id] = new_balance
        return new_balance

    async def get_balance(self, user_id: UserId) -> UserBalance:
        async with self.lock:
            return self.balances.get(user_id, 0)

    async def get_balances(self) -> dict[UserId, int]:
        async with self.lock:
            balances_shallow_copy = self.balances.copy()
        return balances_shallow_copy
