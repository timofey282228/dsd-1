from typing import override

import httpx

from . import (
    COUNTER_SERVICE_ENDPOINT,
    AllUserBalances,
    TransactionRequest,
    UserBalance,
    UserId,
    _Timed,
)
from .abstract_counter_service import AbstractCounterService


class HttpCounterService(_Timed, AbstractCounterService):
    def __init__(self, http_client: httpx.AsyncClient):
        super().__init__()
        self.http_client = http_client

    @override
    async def execute_transaction(
        self,
        user_id: UserId,
        transaction: TransactionRequest,
    ) -> UserBalance:
        counter_response = (
            await self.timed(
                self.http_client.post(
                    COUNTER_SERVICE_ENDPOINT.copy_with(path=f"/users/{user_id}"),
                    headers={"content-type": "application/json"},
                    content=transaction.model_dump_json(),
                )
            )
        ).raise_for_status()

        return UserBalance.model_validate_json(counter_response.read())

    @override
    async def get_balance(self, user_id: UserId) -> UserBalance:
        balance_response = (
            await self.http_client.get(
                COUNTER_SERVICE_ENDPOINT.copy_with(path=f"/users/{user_id}")
            )
        ).raise_for_status()

        return UserBalance.model_validate_json(balance_response.read())

    @override
    async def get_all_balances(self) -> AllUserBalances:
        balances_response = (
            await self.http_client.get(
                COUNTER_SERVICE_ENDPOINT.copy_with(path=f"/users")
            )
        ).raise_for_status()

        return AllUserBalances.model_validate_json(balances_response.read())
