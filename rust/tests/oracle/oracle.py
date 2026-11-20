"""Differential-test oracle: run the Python reference over a batch of cases.

Reads one JSON document on stdin and writes one JSON document on stdout. The Rust test
(`tests/differential.rs`) generates the cases, asks this script for the reference answers, and
compares byte for byte. The Python checkout is on PYTHONPATH (`<checkout>/src`).

    {"toon": [{"value": ..., "delimiter": ",", "indent": 2}, ...],
     "recovery": [{"recovery": {...}, "tool": "x-axi", "other": "y-axi"}, ...]}
"""
import json
import sys

from axi_toolkit import toon
from axi_toolkit.errors import Recovery
from axi_toolkit.render import cli, prose


def main() -> None:
    request = json.load(sys.stdin)
    out = {"toon": [], "recovery": []}
    for case in request.get("toon", []):
        out["toon"].append(
            toon.encode(case["value"], indent=case["indent"], delimiter=case["delimiter"])
        )
    for case in request.get("recovery", []):
        recovery = Recovery.from_dict(case["recovery"])
        row = {}
        for slot in ("tool", "other"):
            name = case[slot]
            row[slot] = {
                "line": cli.line(recovery, name),
                "sentence": prose.sentence(recovery, name),
            }
        row["parsed_back"] = cli.parse(row["tool"]["line"], case["tool"]).as_dict()
        out["recovery"].append(row)
    json.dump(out, sys.stdout, ensure_ascii=False)


main()
