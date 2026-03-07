#!/usr/bin/env python3

import argparse
import csv
from typing import TypedDict


class Entry(TypedDict):
    total: float
    rate: float
    logging: float
    count: float


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument("measurements_csv")
    args = argparser.parse_args()

    with open(args.measurements_csv, "rt") as file:
        entries: tuple[Entry] = tuple(csv.DictReader(file))
        total_avg = sum(
            map(
                lambda entry: float(entry["total"]),
                entries,
            )
        ) / len(entries)
        rate_avg = sum(
            map(
                lambda entry: float(entry["rate"]),
                entries,
            )
        ) / len(entries)
        logging_avg = sum(
            map(
                lambda entry: float(entry["logging"]),
                entries,
            )
        ) / len(entries)
        count_avg = sum(
            map(
                lambda entry: float(entry["count"]),
                entries,
            )
        ) / len(entries)

        print(
            f"""Average total time spend: {total_avg:.4f}
Average rate: {rate_avg:.4f} r/s
Average logging time spent: {logging_avg:.4f} ({logging_avg/total_avg:.4%} total)
Average count time spent: {count_avg:.4f} ({count_avg/total_avg:.4%} total)"""
        )
