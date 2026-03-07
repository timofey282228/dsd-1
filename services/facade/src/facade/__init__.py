import asyncio
import datetime
import time
from collections.abc import Coroutine
from contextlib import asynccontextmanager
from typing import Annotated, Mapping
from uuid import UUID, uuid7

import httpx
import pydantic
from fastapi import Body, FastAPI, Query, Request

LOGGING_SERVICE_URL = httpx.URL("http://logging")
COUNTER_SERVICE_ENDPOINT = httpx.URL("http://counter")

# MARK: models

type UserId = int


class TransactionRequest(pydantic.BaseModel):
    amount: int


class TransactionData(TransactionRequest):
    user_id: UserId
    timestamp: datetime.datetime = pydantic.Field(
        default_factory=datetime.datetime.now()
    )


class TransactionResult(pydantic.BaseModel):
    balance: int
    transaction_id: UUID


class UserBalance(pydantic.BaseModel):
    balance: int


class Transaction(TransactionData):
    transaction_id: UUID


class TransactionList(pydantic.RootModel):
    root: list[Transaction]


class UserTransaction(pydantic.BaseModel):
    amount: int
    timestamp: datetime.datetime = pydantic.Field(
        default_factory=datetime.datetime.now()
    )
    transaction_id: UUID


class UserTransactionList(pydantic.RootModel):
    root: list[UserTransaction]


class UserStatement(pydantic.BaseModel):
    balance: int
    transactions: UserTransactionList


class AllUserBalances(pydantic.RootModel):
    root: dict[UserId, int]


class ServiceTimeStats(pydantic.BaseModel):
    countersvc: int
    """Total ns spent waiting for countersvc responses"""
    logsvc: int
    """Total ns spent waiting for logsvc responses"""


class TimedTransactionResult(TransactionResult):
    timings: ServiceTimeStats


#  MARK: service interfaces


class _Timed:
    def __init__(self):
        self.__lock = asyncio.Lock()
        self._total_time = 0.0
        """ns"""

    async def timed[T](self, coroutine: Coroutine[None, None, T]) -> T:
        start_ns = time.perf_counter_ns()
        result = await coroutine
        elapsed_ns = time.perf_counter_ns() - start_ns
        async with self.__lock:
            self._total_time += elapsed_ns
        return result

    async def get_measured_time(self):
        async with self.__lock:
            return self._total_time


class LoggingService(_Timed):
    def __init__(self, http_client: httpx.AsyncClient):
        super().__init__()
        self.http_client = http_client

    async def add_transaction(
        self,
        transaction_id: UUID,
        logged_transaction_data: TransactionData,
    ):
        (
            await self.timed(
                self.http_client.post(
                    LOGGING_SERVICE_URL.copy_with(
                        path=f"/transactions/{transaction_id}"
                    ),
                    headers={"content-type": "application/json"},
                    content=logged_transaction_data.model_dump_json(),
                )
            )
        ).raise_for_status()

    async def get_transactions(self, user_id: UserId) -> TransactionList:
        transactions_response = (
            await self.http_client.get(
                LOGGING_SERVICE_URL.copy_with(path=f"/users/{user_id}/transactions"),
            )
        ).raise_for_status()

        transactions = TransactionList.model_validate_json(transactions_response.read())
        return transactions


class CounterService(_Timed):
    def __init__(self, http_client: httpx.AsyncClient):
        super().__init__()
        self.http_client = http_client

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

    async def get_balance(self, user_id: UserId) -> UserBalance:
        balance_response = (
            await self.http_client.get(
                COUNTER_SERVICE_ENDPOINT.copy_with(path=f"/users/{user_id}")
            )
        ).raise_for_status()

        return UserBalance.model_validate_json(balance_response.read())

    async def get_all_balances(self) -> AllUserBalances:
        balances_response = (
            await self.http_client.get(
                COUNTER_SERVICE_ENDPOINT.copy_with(path=f"/users")
            )
        ).raise_for_status()

        return AllUserBalances.model_validate_json(balances_response.read())


#  MARK: API


class ApiState(Mapping):
    logging_service: LoggingService
    counter_service: CounterService


@asynccontextmanager
async def api_lifespan(_: FastAPI):
    async with httpx.AsyncClient() as http_client:
        yield {
            "logging_service": LoggingService(http_client=http_client),
            "counter_service": CounterService(http_client=http_client),
        }


api = FastAPI(lifespan=api_lifespan)


# MARK: POST


async def _untimed_transaction(
    transaction_id: UUID,
    logging_coro: Coroutine,
    counter_coro: Coroutine[None, None, UserBalance],
) -> TransactionResult:
    async with asyncio.TaskGroup() as backend_tasks:
        logging_task = backend_tasks.create_task(logging_coro)
        counter_task = backend_tasks.create_task(counter_coro)

    logging_task.result()
    balance = counter_task.result()

    return TransactionResult(
        balance=balance.balance,
        transaction_id=transaction_id,
    )


async def timed[T](coro: Coroutine[None, None, T]) -> tuple[int, T]:
    """Run `coro` and return execution tim in ns `coro`'s result."""
    start_ns = time.perf_counter_ns()
    result = await coro
    elapsed = time.perf_counter_ns() - start_ns
    return elapsed, result


async def _timed_transaction(
    transaction_id: UUID,
    logging_coro: Coroutine,
    counter_coro: Coroutine[None, None, UserBalance],
) -> TimedTransactionResult:
    async with asyncio.TaskGroup() as backend_tasks:
        logging_task = backend_tasks.create_task(timed(logging_coro))
        counter_task = backend_tasks.create_task(timed(counter_coro))

    logging_time, _ = logging_task.result()
    counter_time, balance = counter_task.result()

    return TimedTransactionResult(
        balance=balance.balance,
        transaction_id=transaction_id,
        timings=ServiceTimeStats(
            countersvc=counter_time,
            logsvc=logging_time,
        ),
    )


@api.post("/users/{user_id}/amount")
async def post_user_amount(
    request: Request,
    user_id: int,
    amount_transact: Annotated[TransactionRequest, Body()],
    timed: Annotated[bool, Query()] = False,
) -> TransactionResult | TimedTransactionResult:
    request: Request[ApiState] = request
    transaction_timestamp = datetime.datetime.now()
    transaction_id = uuid7()

    # execute asynchronous task in parallel and wait until both finish
    logging_coro = request.state.logging_service.add_transaction(
        transaction_id=transaction_id,
        logged_transaction_data=TransactionData(
            amount=amount_transact.amount,
            user_id=user_id,
            timestamp=transaction_timestamp,
        ),
    )

    counter_coro = request.state.counter_service.execute_transaction(
        user_id=user_id,
        transaction=amount_transact,
    )

    if timed:
        return await _timed_transaction(
            transaction_id,
            logging_coro,
            counter_coro,
        )
    else:
        return await _untimed_transaction(
            transaction_id,
            logging_coro,
            counter_coro,
        )


# MARK: GET


@api.get("/users/{user_id}")
async def get_user_account(
    request: Request,
    user_id: int,
) -> UserStatement:
    request: Request[ApiState] = request

    async with asyncio.TaskGroup() as backend_tasks:
        balance_task = backend_tasks.create_task(
            request.state.counter_service.get_balance(user_id=user_id)
        )
        transactions_task = backend_tasks.create_task(
            request.state.logging_service.get_transactions(user_id=user_id)
        )

    balance, transactions = balance_task.result(), transactions_task.result()

    return UserStatement(
        balance=balance.balance,
        transactions=UserTransactionList(
            list(
                map(
                    lambda transaction: UserTransaction(
                        amount=transaction.amount,
                        timestamp=transaction.timestamp,
                        transaction_id=transaction.transaction_id,
                    ),
                    transactions.root,
                )
            )
        ),
    )


@api.get("/balances")
async def get_accounts(request: Request) -> AllUserBalances:
    request: Request[ApiState] = request
    user_balance = await request.state.counter_service.get_all_balances()
    return user_balance


# MARK: stats


@api.get("/timing_stats")
async def request_proc_time(request: Request):
    request: Request[ApiState] = request
    return ServiceTimeStats(
        countersvc=await request.state.counter_service.get_measured_time(),
        logsvc=await request.state.logging_service.get_measured_time(),
    )
