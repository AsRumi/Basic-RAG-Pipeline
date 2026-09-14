"""
Inspect and roll back supersessions.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
from store import documents
from supersede import read_log

def stamp(when):
    if not when:
        return "-"
    return datetime.fromtimestamp(when, timezone.utc).strftime("%Y-%m-%d %H:%M")

def parse_since(value):
    try:
        return float(value)
    except ValueError:
        pass

    try:
        as_of = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise SystemExit(f"--since must be YYYY-MM-DD or an epoch timestamp, got '{value}'")

    return as_of.replace(tzinfo = timezone.utc).timestamp()

def show_list():
    records = documents.get(where = {"status": "superseded"})
    rows = sorted(zip(records["ids"], records["metadatas"]),
                  key = lambda row: row[1]["superseded_at"])

    if not rows:
        print("Nothing is superseded.")
        return

    for id, metadata in rows:
        print(id)
        print(f"    replaced by {metadata['superseded_by'] or '-'} on {stamp(metadata['superseded_at'])}")

    print(f"\n{len(rows)} superseded of {documents.count()} stored")

def show_stats():
    records = documents.get()
    counts = Counter((metadata["source"], metadata["status"]) for metadata in records["metadatas"])
    totals = Counter(metadata["status"] for metadata in records["metadatas"])
    width = max([len(source) for source, _ in counts] + [len("total")])

    print(f"{'source':{width}} {'active':>8} {'superseded':>12}")
    for source in sorted({source for source, _ in counts}):
        print(f"{source:{width}} {counts[(source, 'active')]:>8} {counts[(source, 'superseded')]:>12}")
    print(f"{'total':{width}} {totals['active']:>8} {totals['superseded']:>12}")

def applied_lines(since):
    lines = [pair for pair in read_log() if pair.get("applied")]
    if since is None:
        return lines
    return [pair for pair in lines if pair["applied_at"] >= since]

def replay(pairs, expected, patch, verb, skipped):
    changed = 0
    for pair in pairs:
        record = documents.get(ids = [pair["old_id"]])

        if not record["ids"]:
            print(f"  not in the store, skipped: {pair['old_id']}")
            continue

        metadata = record["metadatas"][0]
        if metadata["status"] != expected:
            print(f"  {skipped}, skipped: {pair['old_id']}")
            continue

        documents.update(ids = [pair["old_id"]], metadatas = [{**metadata, **patch(pair)}])
        print(f"  {verb}: {pair['old_id']}")
        changed += 1

    return changed

def rollback(since):
    lines = applied_lines(since)
    if not lines:
        print("No applied supersessions in the log to roll back.")
        return

    changed = replay(reversed(lines), "superseded",
                     lambda pair: {"status": "active",
                                   "superseded_by": "",
                                   "superseded_at": 0.0},
                     "restored", "already active")

    print(f"\n{changed} of {len(lines)} logged supersessions rolled back, "
          f"{documents.count()} stored")

def reapply(since):
    lines = applied_lines(since)
    if not lines:
        print("No applied supersessions in the log to replay.")
        return

    # an ingest cannot redo this: its chunks are already stored, so nothing gets nominated
    changed = replay(lines, "active",
                     lambda pair: {"status": "superseded",
                                   "superseded_by": pair["new_id"],
                                   "superseded_at": pair["applied_at"]},
                     "superseded", "already superseded")

    print(f"\n{changed} of {len(lines)} logged supersessions replayed, "
          f"{documents.count()} stored")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action = "store_true",
                        help = "Show superseded records and what replaced them.")
    parser.add_argument("--stats", action = "store_true",
                        help = "Counts by source and status.")
    parser.add_argument("--rollback", action = "store_true",
                        help = "Replay the log backwards, restoring superseded records to active.")
    parser.add_argument("--reapply", action = "store_true",
                        help = "Replay the log forwards, undoing a --rollback.")
    parser.add_argument("--since",
                        help = "Limit --rollback or --reapply to supersessions applied on or "
                               "after YYYY-MM-DD or an epoch timestamp.")
    args, _ = parser.parse_known_args()

    if not (args.list or args.stats or args.rollback or args.reapply):
        parser.error("choose at least one of --list, --stats, --rollback, --reapply")

    if args.rollback and args.reapply:
        parser.error("--rollback and --reapply cannot be combined")

    if args.list:
        show_list()

    if args.stats:
        show_stats()

    if args.rollback:
        rollback(parse_since(args.since) if args.since else None)

    if args.reapply:
        reapply(parse_since(args.since) if args.since else None)
