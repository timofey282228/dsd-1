from abc import ABCMeta
from asyncio.locks import Lock
from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import Annotated

import pydantic
from fastapi import Body, FastAPI, Request

#  MARK: models

type UserId = int


class Transaction(pydantic.BaseModel):
    amount: int


class UserBalance(pydantic.BaseModel):
    balance: int


class AllUserBalances(pydantic.RootModel):
    root: dict[UserId, int]


#  MARK: internals


class Counter:
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


#  MARK: API


class ApiState(Mapping, metaclass=ABCMeta):
    counter: Counter


@asynccontextmanager
async def api_lifespan(_: FastAPI):
    yield {"counter": Counter()}


api = FastAPI(lifespan=api_lifespan)

# MARK: POST


@api.post("/users/{user_id}")
async def post_balance(
    request: Request,
    user_id: UserId,
    transaction: Annotated[Transaction, Body()],
) -> UserBalance:
    request: Request[ApiState] = request  # type: ignore[no-redef]
    balance = await request.state.counter.execute_transaction(
        user_id=user_id,
        transaction=transaction,
    )
    return UserBalance(balance=balance)


# MARK: GET


@api.get("/users/{user_id}")
async def get_balance(
    request: Request,
    user_id: UserId,
) -> UserBalance:
    request: Request[ApiState] = request  # type: ignore[no-redef]
    return UserBalance(
        balance=await request.state.counter.get_balance(user_id=user_id),
    )


@api.get("/users")
async def get_all_balances(
    request: Request,
) -> AllUserBalances:
    request: Request[ApiState] = request  # type: ignore[no-redef]
    return AllUserBalances(await request.state.counter.get_balances())
