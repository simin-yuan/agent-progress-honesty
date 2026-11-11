"""Experiment CLI.

Examples
--------
python -m bench.run --models deepseek-flash --tasks A01,B01 --runs 1 --out logs/raw/smoke
python -m bench.run --models deepseek-flash,deepseek-pro,qwen3.5-9b --runs 3 --out logs/raw/full
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import BUDGET_USD, DEFAULT_MODELS, MAX_TOOL_TURNS, MODELS
from .env import load_tasks
from .llm import make_client
from .runner import run_episode
from .config import ROOT


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--models", default=",".join(DEFAULT_MODELS))
    p.add_argument("--tasks", default="all")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--out", default=os.path.join(ROOT, "logs", "raw", "full"))
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--ollama-workers", type=int, default=1)
    p.add_argument("--max-turns", type=int, default=MAX_TOOL_TURNS)
    p.add_argument("--intervention", choices=["baseline", "I1", "I2"], default="baseline")
    p.add_argument("--budget", type=float, default=BUDGET_USD)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    tasks_path = os.path.join(ROOT, "tasks", "tasks.json")
    tasks = load_tasks(tasks_path)
    if args.tasks != "all":
        wanted = {t.strip() for t in args.tasks.split(",") if t.strip()}
        tasks = [t for t in tasks if t["id"] in wanted]
        missing = wanted - {t["id"] for t in tasks}
        if missing:
            print(f"unknown task ids: {sorted(missing)}", file=sys.stderr)
            return 2
    model_labels = [m.strip() for m in args.models.split(",") if m.strip()]
    for m in model_labels:
        if m not in MODELS:
            print(f"unknown model: {m}", file=sys.stderr)
            return 2

    os.makedirs(args.out, exist_ok=True)
    jobs = []
    for spec_label in model_labels:
        for task in tasks:
            for run_idx in range(1, args.runs + 1):
                path = os.path.join(args.out, spec_label, f"{task['id']}-r{run_idx}.json")
                if os.path.exists(path):
                    continue
                jobs.append((spec_label, task, run_idx, path))
    print(f"planned episodes: {len(jobs)} (skipping completed files)")
    if args.dry_run:
        return 0

    lock = threading.Lock()
    spent = 0.0
    done = 0
    failures = 0
    started = time.time()

    def work(job):
        spec_label, task, run_idx, path = job
        spec = MODELS[spec_label]
        client = make_client(spec)
        return run_episode(client, spec, task, run_idx, args.out, args.intervention)

    # Group by provider so local inference is not oversubscribed.
    jobs_ds = [j for j in jobs if MODELS[j[0]].provider == "deepseek"]
    jobs_local = [j for j in jobs if MODELS[j[0]].provider == "ollama"]

    def consume(futures):
        nonlocal spent, done, failures
        for fut in as_completed(futures):
            job = futures[fut]
            try:
                rec = fut.result()
            except Exception as exc:  # noqa: BLE001
                failures += 1
                with lock:
                    print(f"[FAIL] {job[0]} {job[1]['id']} r{job[2]}: {exc}")
                continue
            with lock:
                spent += rec["cost_usd"]
                done += 1
                flag = "ERR" if rec["protocol_error"] else "ok "
                print(
                    f"[{flag}] {rec['episode_id']:<28} actual={int(bool(rec['actual_done_final']))} "
                    f"r0={str(rec['status_initial']):<7} r2={str(rec['status_final']):<7} "
                    f"c0={(rec['reports'].get('r0') or {}).get('confidence')} "
                    f"t={rec['duration_s']}s ${rec['cost_usd']:.4f} total=${spent:.4f}"
                )
                if spent > args.budget:
                    print(f"!! budget exceeded: ${spent:.2f} > ${args.budget:.2f}", file=sys.stderr)

    if jobs_ds:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futs = {pool.submit(work, j): j for j in jobs_ds}
            consume(futs)
    if jobs_local:
        with ThreadPoolExecutor(max_workers=max(1, args.ollama_workers)) as pool:
            futs = {pool.submit(work, j): j for j in jobs_local}
            consume(futs)

    elapsed = time.time() - started
    print(f"\ndone={done} failed={failures} elapsed={elapsed/60:.1f} min spent=${spent:.4f}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
