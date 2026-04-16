import asyncio
import datetime
import functools
import logging
import random
import socket
import string
import time
from abc import ABCMeta
from collections.abc import Coroutine, Mapping
from contextlib import asynccontextmanager
from typing import Annotated, Awaitable, Callable, Optional
from uuid import UUID, uuid7

import httpx
import pydantic
from config_server_client import ConfigServerClient
from consul import Check, Consul
from fastapi import Body, FastAPI, Query, Request
from hazelcast import HazelcastClient
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_NAME = "facade"
SERVICE_PORT = 80
HEALTHCHECK_PATH = "/health"
MAX_ETO = 32

logger = logging.getLogger(__name__)

# MARK: models

type UserId = int


class TransactionRequest(pydantic.BaseModel):
    amount: int


class TransactionData(TransactionRequest):
    user_id: UserId
    timestamp: datetime.datetime = pydantic.Field(
        default_factory=lambda: datetime.datetime.now()
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
        default_factory=lambda: datetime.datetime.now()
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


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_prefix="FACADE_",
        env_prefix_target="alias",
        validate_default=True,
    )

    hazelcast_cluster: str = pydantic.Field(alias="HAZELCAST_CLUSTER")
    hazelcast_cluster_members: list[str] = pydantic.Field(
        default=["127.0.0.1", "hazelcast"], alias="HAZELCAST_CLUSTER_MEMBERS"
    )

    config_server_netloc: str = pydantic.Field(alias="CONFIGSERVER_NETLOC")
    consul_host: Optional[str] = pydantic.Field(default=None, alias="CONSUL_HOST")
    consul_port: Optional[int] = pydantic.Field(default=None, alias="CONSUL_PORT")
    consul_token: Optional[str] = pydantic.Field(default=None, alias="CONSUL_TOKEN")


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
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        instance_generator: AbstractRandomInstanceGenerator,
    ):
        super().__init__()
        self.http_client = http_client
        self.instance_generator: AbstractRandomInstanceGenerator = instance_generator

    async def instance(self) -> ServiceInstance:
        return await self.instance_generator.random_instance()

    @staticmethod
    async def _with_eto_retry_on[O](
        exception_class: type[Exception],
        operation_builder: Callable[[], Awaitable[O]],
        on_error: Callable[[Exception], None],
    ) -> O:
        eto = 1 / 8
        while True:
            try:
                return await operation_builder()
            except exception_class as e:
                on_error(e)

            await asyncio.sleep(eto)
            if eto < MAX_ETO:
                eto *= 2

    async def _post_add_transaction(
        self,
        transaction_id: UUID,
        logged_transaction_data: TransactionData,
    ):
        async with (await self.instance()).refreshing_on(
            (httpx.TransportError,)
        ) as instance_address:
            host, port = instance_address
            url = httpx.URL(
                scheme="http",
                host=host,
                port=port,
                path=f"/transactions/{transaction_id}",
            )
            (
                await self.timed(
                    self.http_client.post(
                        url,
                        headers={"content-type": "application/json"},
                        content=logged_transaction_data.model_dump_json(),
                    )
                )
            ).raise_for_status()

    async def add_transaction(
        self,
        transaction_id: UUID,
        logged_transaction_data: TransactionData,
    ):
        await self._with_eto_retry_on(
            httpx.TransportError,
            operation_builder=functools.partial(
                self._post_add_transaction,
                transaction_id=transaction_id,
                logged_transaction_data=logged_transaction_data,
            ),
            on_error=lambda e: logging.exception(
                "Add transaction %s/%s: exception",
                logged_transaction_data.user_id,
                transaction_id,
                exc_info=e,
            ),
        )

    async def _get_get_transactions(self, user_id: UserId) -> TransactionList:
        async with (await self.instance()).refreshing_on(
            (httpx.TransportError,)
        ) as instance_address:
            host, port = instance_address
            url = httpx.URL(
                scheme="http",
                host=host,
                port=port,
                path=f"/users/{user_id}/transactions",
            )
            transactions_response = (await self.http_client.get(url)).raise_for_status()

        transactions = TransactionList.model_validate_json(transactions_response.read())
        return transactions

    async def get_transactions(self, user_id: UserId) -> TransactionList:
        return await self._with_eto_retry_on(
            httpx.TransportError,
            operation_builder=functools.partial(
                self._get_get_transactions,
                user_id=user_id,
            ),
            on_error=lambda e: logging.exception(
                "Get transactions for %s: exception",
                user_id,
                exc_info=e,
            ),
        )


#  MARK: API


class ApiState(Mapping, metaclass=ABCMeta):
    logging_service: LoggingService
    counter_service: AbstractCounterService
    config: Config


@asynccontextmanager
async def api_lifespan(_: FastAPI):
    service_config = Config()
    consul = Consul(
        host=service_config.consul_host,
        port=service_config.consul_port,
        token=service_config.consul_token,
    )

    hz_client = HazelcastClient(
        client_name=SERVICE_NAME,
        cluster_name=service_config.hazelcast_cluster,
        cluster_members=service_config.hazelcast_cluster_members,
    )

    config_server_client = ConfigServerClient(service_config.config_server_netloc)

    consul_service_id = (
        SERVICE_NAME + "-" + "".join(random.sample(string.ascii_uppercase, 7))
    )
    consul_service_address = socket.gethostbyname(socket.gethostname())
    logger.info("Registering with Consul server as %s", consul_service_id)

    assert consul.agent.service.register(
        name=SERVICE_NAME,
        service_id=consul_service_id,
        address=consul_service_address,
        port=SERVICE_PORT,
        token=service_config.consul_token,
        check=Check.http(
            url=f"http://{consul_service_address}:{SERVICE_PORT}{HEALTHCHECK_PATH}",
            interval="5s",
            timeout="2s",
            deregister="15s",
        ),
    ), "Consul service must be registered successfully"

    async with httpx.AsyncClient() as http_client:
        yield {
            "logging_service": LoggingService(
                http_client=http_client,
                instance_generator=ConsulRandomInstanceGenerator("logging", consul),
            ),
            # "counter_service": HttpCounterService(http_client=http_client),
            "counter_service": HazelcastQueueCounterService(
                hz_client=hz_client,
                instance_generator=ConsulRandomInstanceGenerator("counter", consul),
            ),
        }
        consul.agent.service.deregister(
            consul_service_id, token=service_config.consul_token
        )
    hz_client.shutdown()


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
        counter_task = backend_tasks.crate_task(timed(counter_coro))

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
    request: Request[ApiState] = request  # type: ignore[no-redef]
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
    request: Request[ApiState] = request  # type: ignore[no-redef]

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
    request: Request[ApiState] = request  # type: ignore[no-redef]
    user_balance = await request.state.counter_service.get_all_balances()
    return user_balance


# MARK: stats


@api.get("/timing_stats")
async def request_proc_time(request: Request):
    request: Request[ApiState] = request  # type: ignore[no-redef]
    return ServiceTimeStats(
        countersvc=await request.state.counter_service.get_measured_time(),
        logsvc=await request.state.logging_service.get_measured_time(),
    )


@api.get(HEALTHCHECK_PATH)
async def health():
    return True


from .abstract_counter_service import AbstractCounterService
from .abstract_random_instance_generator import (
    AbstractRandomInstanceGenerator,
    ServiceInstance,
)
from .consul_instance_generator import ConsulRandomInstanceGenerator
from .hazelcast_queue_counter_service import HazelcastQueueCounterService
