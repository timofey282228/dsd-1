import datetime
from abc import ABCMeta
from asyncio.locks import Lock
from collections.abc import Mapping
from contextlib import asynccontextmanager
from itertools import starmap
from typing import override
from uuid import UUID

import pydantic
from fastapi import FastAPI, Request

#  MARK: models

type UserId = int


class TransactionData(pydantic.BaseModel):
    user_id: UserId
    amount: int
    timestamp: datetime.datetime


class Transaction(TransactionData):
    transaction_id: UUID


class TransactionList(pydantic.RootModel):
    root: list[Transaction]


#  MARK: internals


class Logging:
    def __init__(self):
        self.lock = Lock()
        self.transactions: dict[UUID, TransactionData] = {}

    async def add_transaction(
        self,
        transaction_id: UUID,
        transaction_data: TransactionData,
    ):
        async with self.lock:
            self.transactions[transaction_id] = transaction_data

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


#  MARK: API


class ApiState(Mapping, metaclass=ABCMeta):
    logging: Logging


@asynccontextmanager
async def api_lifespan(_: FastAPI):
    yield {"logging": Logging()}


api = FastAPI(lifespan=api_lifespan)

# MARK: POST


@api.post("/transactions/{transaction_id}")
async def post_transaction(
    request: Request,
    transaction_id: UUID,
    transaction_data: TransactionData,
):
    request: Request[ApiState] = request  # type: ignore[no-redef]
    await request.state.logging.add_transaction(
        transaction_id=transaction_id,
        transaction_data=transaction_data,
    )


# MARK: GET


@api.get("/users/{user_id}/transactions")
async def get_transactions(
    request: Request,
    user_id: UserId,
) -> TransactionList:
    request: Request[ApiState] = request  # type: ignore[no-redef]
    return await request.state.logging.get_user_transactions(user_id=user_id)
