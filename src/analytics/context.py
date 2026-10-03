"""Explicit context for generic SELECT-only validator entry points."""
import argparse


def context_id(value):
    if not value.isascii() or not value.isdecimal() or not 0 < int(value) < 2**32:
        raise argparse.ArgumentTypeError("Context ID must be a positive UInt32")
    return int(value)


def add_context_arguments(parser):
    parser.add_argument("--competition-id", required=True, type=context_id)
    parser.add_argument("--season-id", required=True, type=context_id)


def context_from_args(args):
    return {"competition_id": args.competition_id, "season_id": args.season_id}
