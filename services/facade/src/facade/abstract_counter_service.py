from abc import ABCMeta

from . import AllUserBalances, TransactionRequest, UserBalance, UserId


class AbstractCounterService(metaclass=ABCMeta):
    async def execute_transaction(
        self,
        user_id: UserId,
        transaction: TransactionRequest,
    ) -> UserBalance: ...

    async def get_balance(self, user_id: UserId) -> UserBalance: ...

    async def get_all_balances(self) -> AllUserBalances: ...
