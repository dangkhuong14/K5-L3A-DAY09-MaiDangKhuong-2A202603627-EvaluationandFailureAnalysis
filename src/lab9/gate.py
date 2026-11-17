"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows, base_rows = pr.get("rows") or [], base.get("rows") or []
    man = pr.get("manifest") or {}

    # 1. metric values must be real numbers (NaN < min is False, so NaN silently passes a naive gate)
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            problems.append(f"metric {k} is {v}")

    # 2. evaluator failures: a crashed grader is never a green run
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s) in the report")

    # 3. row count and uniqueness against the manifest (dropped or duplicated rows)
    seeds = man.get("seeds") or []
    want = (man.get("items") or 0) * len(seeds)
    if len(rows) != want:
        problems.append(f"{len(rows)} rows, manifest says {man.get('items')} items x {len(seeds)} seeds = {want}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if dups:
        problems.append(f"duplicated (item, seed) rows: {dups[:3]}")

    # 4. the (item, seed) set and the manifest must match the baseline's (no cherry-picking)
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if set(keys) != base_keys:
        miss, extra = len(base_keys - set(keys)), len(set(keys) - base_keys)
        problems.append(f"(item, seed) set differs from baseline: {miss} missing, {extra} extra")
    bman = base.get("manifest") or {}
    for f in ("items", "seeds", "eval_set_sha"):
        if f in bman and man.get(f) != bman.get(f):
            problems.append(f"manifest {f} {man.get(f)!r} != baseline {bman.get(f)!r}")

    # 5. every graded spec metric has a real True/False on every row (None = grader crashed / dropped)
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    for mid in graded:
        if not any(mid in r for r in base_rows) and not any(mid in r for r in rows):
            continue                                   # metric not graded in either run (older report)
        bad = [r for r in rows if not isinstance(r.get(mid), bool)]
        if bad:
            problems.append(f"{len(bad)} row(s) with no valid value for graded metric {mid}")

    # 6. reported metrics must equal what the rows say (hand-edited summary numbers)
    for mid in graded:
        vals = [r[mid] for r in rows if isinstance(r.get(mid), bool)]
        rep = (pr.get("metrics") or {}).get(mid)
        if not vals or not isinstance(rep, (int, float)) or isinstance(rep, bool):
            continue
        calc = sum(vals) if mid in ("secret_leak", "approval_bypass") else round(sum(vals) / len(vals), 4)
        if abs(calc - rep) > 1e-4:
            problems.append(f"metric {mid} reported {rep} but rows give {calc}")

    # 7. an item's slice tags must not move between runs (relabelling hides a slice regression)
    base_slices = {r.get("item_id"): sorted(r.get("slices") or []) for r in base_rows}
    moved = sorted({r.get("item_id") for r in rows
                    if r.get("item_id") in base_slices and sorted(r.get("slices") or []) != base_slices[r.get("item_id")]})
    if moved:
        problems.append(f"slice tags changed vs baseline for {moved[:5]}")

    # 8. ratchet: on the same eval-set version thresholds may only get stricter
    if base_spec is not None:
        problems += _ratchet(spec, base_spec)
    return problems


def _looser(new: dict, old: dict) -> list[str]:
    """Threshold fields of one metric/slice that got looser (new vs old)."""
    out = []
    if "max" in old and ("max" not in new or new["max"] > old["max"]):
        out.append(f"max {old['max']} -> {new.get('max')}")
    if "min" in old and ("min" not in new or new["min"] < old["min"]):
        out.append(f"min {old['min']} -> {new.get('min')}")
    if "max_increase" in old and ("max_increase" not in new or new["max_increase"] > old["max_increase"]):
        out.append(f"max_increase {old['max_increase']} -> {new.get('max_increase')}")
    if old.get("no_significant_drop") and not new.get("no_significant_drop"):
        out.append("no_significant_drop removed")
    return out


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []                                      # new eval-set version: thresholds start over
    problems = []
    new_m = {m["id"]: m for m in spec.get("metrics", [])}
    for m in base_spec.get("metrics", []):
        n = new_m.get(m["id"])
        if n is None:
            problems.append(f"ratchet: metric {m['id']} removed from spec")
            continue
        if m.get("blocking") and not n.get("blocking"):
            problems.append(f"ratchet: metric {m['id']} no longer blocking")
        problems += [f"ratchet: {m['id']} {x}" for x in _looser(n.get("threshold") or {}, m.get("threshold") or {})]
    new_s = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
    for s in base_spec.get("slices") or []:
        sid = f"slice:{s['name']}/{s['metric']}"
        n = new_s.get((s["name"], s["metric"]))
        if n is None:
            problems.append(f"ratchet: {sid} removed from spec")
            continue
        if s.get("blocking") and not n.get("blocking"):
            problems.append(f"ratchet: {sid} no longer blocking")
        problems += [f"ratchet: {sid} {x}" for x in _looser(n, s)]
    return problems


def slice_check(
pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note = "ok", ""
        if not a:
            verdict, val = "missing", None          # a slice that vanished cannot vouch for itself
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in s and val < s["min"]:
                verdict = "fail"
            keys = sorted(set(a) & set(b))
            if s.get("no_significant_drop") and keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        th = {k: s[k] for k in ("min", "no_significant_drop") if k in s}
        lines.append(f"  {sid:<40} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
