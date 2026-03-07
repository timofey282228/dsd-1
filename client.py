#!/usr/bin/env python3

import argparse
import csv
import enum
import multiprocessing
import pprint
import time
from typing import Protocol

import httpx
import pydantic
from pydantic.dataclasses import dataclass

SCENARIO_CLIENT_COUNT = 10
SCENARIO_TRANSACTION_COUNT = 10_000
SCENARIO_TRANSACTION_AMOUNT = 1
SCENARIO_2_TARGET_USER = 1


class Args(Protocol):
    scenario: Scenario
    facade_base_url: str
    csv: str


class ServiceTimeStats(pydantic.BaseModel):
    countersvc: float
    """Total seconds spent waiting for countersvc responses"""
    logsvc: float
    """Total seconds spent waiting for logsvc responses"""


@dataclass
class ClientStats:
    total_time: float
    """Total seconds spent making requests"""
    rate: float
    """Requests per second"""
    total_logging_time: float
    """Total seconds spent waiting for logging service"""
    total_count_time: float
    """Total seconds spent waiting for counter service"""


class Client(multiprocessing.Process):
    def __init__(
        self,
        identifier,
        facade_base_url: str,
        n_transactions: int,
        transaction_amount: int,
        transaction_target,
        starting_gun=None,
    ):
        super().__init__()
        self.identifier = identifier
        self.facade_base_url = facade_base_url
        self.n_transactions = n_transactions
        self.transaction_amount = transaction_amount
        self.transaction_target = transaction_target
        self.starting_gun = starting_gun

        self._request_processing_time_ns = 0
        self._logging_time_ns = 0
        self._count_time_ns = 0
        self.receive_pipe, self._write_pipe = multiprocessing.Pipe(duplex=False)

    def _new_http_client(self) -> httpx.Client:
        return httpx.Client(base_url=self.facade_base_url)

    def run(self):
        with self._new_http_client() as client:
            if self.starting_gun:
                self.starting_gun.wait()
            for _ in range(self.n_transactions):
                self._exec_add_request(
                    http_client=client,
                    user_id=self.transaction_target,
                    amount=self.transaction_amount,
                )

        request_processing_time = self._request_processing_time_ns / 10**9
        logging_time = self._logging_time_ns / 10**9
        count_time = self._count_time_ns / 10**9

        self._write_pipe.send(
            ClientStats(
                total_time=request_processing_time,
                rate=self.n_transactions / request_processing_time,
                total_logging_time=logging_time,
                total_count_time=count_time,
            )
        )

    def _exec_add_request(self, http_client: httpx.Client, user_id, amount):
        start_ns = time.perf_counter_ns()
        response = http_client.post(
            url=f"/users/{user_id}/amount?timed=1",
            json={"amount": amount},
        )
        elapsed_ns = time.perf_counter_ns() - start_ns
        self._request_processing_time_ns += elapsed_ns

        response_json = response.raise_for_status().json()
        service_timings = ServiceTimeStats.model_validate(response_json["timings"])

        self._logging_time_ns += service_timings.logsvc
        self._count_time_ns += service_timings.countersvc


class Scenario(enum.StrEnum):
    SCENARIO_1 = "sc1"
    SCENARIO_2 = "sc2"


def scenario_1(args: Args) -> list[ClientStats]:
    clients: list[Client] = []
    client_barrier = multiprocessing.Barrier(SCENARIO_CLIENT_COUNT)
    for i in range(SCENARIO_CLIENT_COUNT):
        client = Client(
            identifier=i,
            facade_base_url=args.facade_base_url,
            n_transactions=SCENARIO_TRANSACTION_COUNT,
            transaction_amount=SCENARIO_TRANSACTION_AMOUNT,
            transaction_target=i,
            starting_gun=client_barrier,
        )
        client.start()
        clients.append(client)

    client_stats = []
    for client in clients:
        client.join()
        client_stats.append(client.receive_pipe.recv())

    with httpx.Client(base_url=args.facade_base_url) as client:
        balances = client.get(url=f"/balances").raise_for_status().json()

    for i in range(SCENARIO_CLIENT_COUNT):
        target_balance = SCENARIO_TRANSACTION_COUNT * SCENARIO_TRANSACTION_AMOUNT
        client_balance = balances[str(i)]
        if client_balance != target_balance:
            print(f"Client {i} balance must be {target_balance}, has {client_balance}")

    return client_stats


def scenario_2(args: Args) -> list[ClientStats]:
    clients: list[Client] = []
    client_barrier = multiprocessing.Barrier(SCENARIO_CLIENT_COUNT)
    for i in range(SCENARIO_CLIENT_COUNT):
        client = Client(
            identifier=i,
            facade_base_url=args.facade_base_url,
            n_transactions=SCENARIO_TRANSACTION_COUNT,
            transaction_amount=SCENARIO_TRANSACTION_AMOUNT,
            transaction_target=SCENARIO_2_TARGET_USER,
            starting_gun=client_barrier,
        )
        client.start()
        clients.append(client)

    client_stats = []
    for client in clients:
        client.join()
        client_stats.append(client.receive_pipe.recv())

    with httpx.Client(base_url=args.facade_base_url) as client:
        balances = client.get(url=f"/balances").raise_for_status().json()

    target_balance = (
        SCENARIO_TRANSACTION_COUNT * SCENARIO_TRANSACTION_AMOUNT * SCENARIO_CLIENT_COUNT
    )
    client_balance = balances[str(SCENARIO_2_TARGET_USER)]
    if client_balance != target_balance:
        print(
            f"User {SCENARIO_2_TARGET_USER} balance must be {target_balance}, has {client_balance}"
        )

    return client_stats


def main(args: Args):
    match args.scenario:
        case Scenario.SCENARIO_1:
            client_stats = scenario_1(args)
        case Scenario.SCENARIO_2:
            client_stats = scenario_2(args)
        case _:
            raise ValueError("Unknown scenario")
    pprint.pp(client_stats)

    if args.csv:
        with open(args.csv, "wt", encoding="utf-8") as csv_output_file:
            csv_writer = csv.DictWriter(
                csv_output_file, fieldnames=("total", "rate", "logging", "count")
            )
            csv_writer.writeheader()
            for client_stat in client_stats:
                csv_writer.writerow(
                    {
                        "total": client_stat.total_time,
                        "rate": client_stat.rate,
                        "logging": client_stat.total_logging_time,
                        "count": client_stat.total_count_time,
                    }
                )


def _configure_argument_parser(parser: argparse.ArgumentParser):
    parser.add_argument("scenario", type=Scenario, choices=tuple(Scenario))
    parser.add_argument("facade_base_url", type=str)
    parser.add_argument("--csv", help="Output client stats CSV path", type=str)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    argparser = argparse.ArgumentParser()
    _configure_argument_parser(argparser)
    args = argparser.parse_args()
    main(args)
