#!/usr/bin/env python3
"""Backfill the benchmark blacklist from past failures.

Scans every *progress*/state JSON (failed_models lists) and every results
file (entries with a failure status / null accuracy) in this directory, then
blacklists each failed model via accuracy_llamacpp.add_to_blacklist. Safe to
run repeatedly — blacklisting is idempotent and won't add duplicate delete
lines to to_delete.txt.

Usage:  python backfill_blacklist.py [--dry-run]
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import accuracy_llamacpp as a  # noqa: E402

DRY = "--dry-run" in sys.argv


def collect_successes():
    """Models that produced a real accuracy score in ANY results file.

    A model that scored even once is usable — its 'failures' elsewhere were
    transient (config/GPU constraints, pre-upgrade engine bugs), NOT permanent.
    These are never blacklisted.
    """
    succeeded = set()
    for path in glob.glob(os.path.join(HERE, "results", "*.json")):
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            continue
        rows = data if isinstance(data, list) else data.get("results", [])
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict) and r.get("accuracy") is not None:
                name = r.get("model_name") or r.get("model")
                if name:
                    succeeded.add(name)
    return succeeded


def collect_failures():
    """Return {model: reason} gathered from progress + results files."""
    failures = {}

    # 1) Progress/state files with explicit failed_models lists
    for path in glob.glob(os.path.join(HERE, "*.json")):
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for m in data.get("failed_models", []) or []:
            failures.setdefault(m, f"failed in {os.path.basename(path)}")

    # 2) Results files — entries that ran but produced no score
    for path in glob.glob(os.path.join(HERE, "results", "*.json")):
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            continue
        rows = data if isinstance(data, list) else data.get("results", [])
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict):
                continue
            name = r.get("model_name") or r.get("model")
            if not name:
                continue
            status = str(r.get("status", "")).lower()
            failed = r.get("accuracy") is None and status not in ("", "ok", "done", "completed")
            if status in ("error", "failed", "timeout") or failed:
                reason = r.get("status") or "no accuracy recorded"
                failures.setdefault(name, f"{reason} ({os.path.basename(path)})")

    return failures


def main():
    failures = collect_failures()
    if not failures:
        print("[OK] No past failures found to backfill.")
        return

    # A model that ever scored is usable — never blacklist it.
    succeeded = collect_successes()
    rescued = [m for m in failures if m in succeeded]
    if rescued:
        print(f"[INFO] Keeping {len(rescued)} model(s) that failed in one run "
              f"but scored in another (transient, not permanent):")
        for m in rescued:
            print(f"  [keep] {m}")
    failures = {m: r for m, r in failures.items() if m not in succeeded}
    if not failures:
        print("\n[OK] Every flagged failure succeeded elsewhere - nothing to blacklist.")
        return

    already = a.load_blacklist()
    new = {m: r for m, r in failures.items() if m not in already}

    print(f"[INFO] Found {len(failures)} failed model(s); "
          f"{len(new)} not yet blacklisted.")
    for m, r in failures.items():
        tag = "NEW " if m in new else "have"
        print(f"  [{tag}] {m:<40} {r}")

    if DRY:
        print("\n[DRY-RUN] No changes written.")
        return
    if not new:
        print("\n[OK] Blacklist already up to date.")
        return

    for m, r in new.items():
        a.add_to_blacklist(m, r)
    print(f"\n[OK] Backfilled {len(new)} model(s) into blacklist.json "
          f"and to_delete.txt")


if __name__ == "__main__":
    main()
