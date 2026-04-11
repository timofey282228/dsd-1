from abc import ABCMeta, abstractmethod

from . import Transaction, UserId


class AbstractCounter(metaclass=ABCMeta):
    @abstractmethod
    async def execute_transaction(
        self,
        user_id: UserId,
        transaction: Transaction,
    ) -> int: ...

    @abstractmethod
    async def get_balance(self, user_id: UserId) -> int: ...

    @abstractmethod
    async def get_balances(self) -> dict[UserId, int]: ...
