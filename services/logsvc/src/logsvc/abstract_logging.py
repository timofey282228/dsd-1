from abc import ABCMeta, abstractmethod
from uuid import UUID

from . import TransactionData, TransactionList, UserId


class AbstractLogging(metaclass=ABCMeta):
    @abstractmethod
    async def add_transaction(
        self,
        transaction_id: UUID,
        transaction_data: TransactionData,
    ): ...

    @abstractmethod
    async def get_user_transactions(self, user_id: UserId) -> TransactionList: ...
