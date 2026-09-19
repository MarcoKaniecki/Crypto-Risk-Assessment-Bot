import json
import csv
import math
import random
import statistics

# === Load inputs ===
with open("data/off-chain_output.json", "r", encoding="utf-8") as f:
    off_chain = json.load(f)

with open("data/on-chain_output.csv", "r", encoding="utf-8") as f:
    snapshots = list(csv.DictReader(f, skipinitialspace=True))

# === Baseline definitions ===
# 'curve' shapes the per-metric deviation: 1.0 = linear, <1.0 = concave
# (penalize early — moderate badness already counts a lot), >1.0 = convex
# (only extreme values count). price_drop uses 0.5 because a 40% crash
# is already a strong signal, not 'half as bad' as a 90% crash.
OFF_CHAIN_SPEC = {
    "hype_level":             {"ideal": 3, "worst": 10, "weight": 1.0, "curve": 1.0},
    "influencer_credibility": {"ideal": 9, "worst": 1,  "weight": 1.0, "curve": 1.0},
    "red_flag_density":       {"ideal": 1, "worst": 10, "weight": 1.5, "curve": 1.0},
    "disclosure_quality":     {"ideal": 9, "worst": 1,  "weight": 1.5, "curve": 1.0},
}

ON_CHAIN_SPEC = {
    "top10_pct":          {"ideal": 0.05,  "worst": 0.50, "weight": 1.5, "curve": 1.0},
    "top50_pct":          {"ideal": 0.15,  "worst": 0.80, "weight": 1.0, "curve": 1.0},
    "holder_count":       {"ideal": 10000, "worst": 100,  "weight": 0.5, "curve": 1.0},
    "holder_growth_rate": {"ideal": 50,    "worst": 3000, "weight": 1.5, "curve": 1.0},
    "price_drop":         {"ideal": 0.00,  "worst": 0.90, "weight": 4.0, "curve": 0.5},
}

BLOCK_WEIGHTS = {"off_chain": 0.4, "on_chain": 0.6}
# Sigmoid centered at 0.35 reflects the prior that scanned tokens skew risky:
# 'moderately deviant' should land in the 60s, not the 50s.
SIGMOID_K, SIGMOID_X0 = 10, 0.35

MC_SAMPLES = 2000
MC_OFF_NOISE = 0.5
MC_ON_NOISE = 0.03


def deviation(value, ideal, worst, curve=1.0):
    """
    Normalize a value to [0, 1] distance from ideal toward worst, then apply
    a curve. curve<1 makes the response concave (early/moderate badness
    already scores high); curve>1 makes it convex (only extremes count).
    """
    if worst == ideal:
        return 0.0
    raw = (value - ideal) / (worst - ideal)
    raw = max(0.0, min(1.0, raw))
    return raw ** curve


def weighted_deviation(values, spec):
    """
    Weighted mean of per-metric deviations, in [0, 1].
    Metrics with value=None are treated as 'not yet measurable' and skipped;
    remaining weights are renormalized so absent data doesn't bias the score.
    """
    active = {k: spec[k] for k in spec if values.get(k) is not None}
    total_w = sum(s["weight"] for s in active.values())
    if total_w == 0:
        return 0.0
    return sum(
        deviation(values[k], active[k]["ideal"], active[k]["worst"], active[k].get("curve", 1.0))
        * active[k]["weight"]
        for k in active
    ) / total_w


def sigmoid(x, k=SIGMOID_K, x0=SIGMOID_X0):
    return 1.0 / (1.0 + math.exp(-k * (x - x0)))


def combine(off_dev, on_dev):
    if on_dev is None:
        return off_dev
    return BLOCK_WEIGHTS["off_chain"] * off_dev + BLOCK_WEIGHTS["on_chain"] * on_dev


def deterministic_score(off_values, on_values=None):
    off_dev = weighted_deviation(off_values, OFF_CHAIN_SPEC)
    on_dev = weighted_deviation(on_values, ON_CHAIN_SPEC) if on_values else None
    return round(sigmoid(combine(off_dev, on_dev)) * 100, 1), off_dev, on_dev


def monte_carlo_score(off_values, on_values=None, n=MC_SAMPLES):
    """Stochastic risk score with Gaussian noise on inputs (skips None values)."""
    risks = []
    for _ in range(n):
        off_sample = {
            k: max(1, min(10, v + random.gauss(0, MC_OFF_NOISE)))
            for k, v in off_values.items()
        }
        if on_values is not None:
            on_sample = {}
            for k, v in on_values.items():
                if v is None:
                    on_sample[k] = None
                elif k == "holder_count":
                    on_sample[k] = max(0, v + random.gauss(0, 200))
                elif k == "holder_growth_rate":
                    on_sample[k] = max(0, v + random.gauss(0, 100))
                else:
                    on_sample[k] = max(0, v + random.gauss(0, MC_ON_NOISE))
        else:
            on_sample = None
        score, _, _ = deterministic_score(off_sample, on_sample)
        risks.append(score)
    return {
        "median": round(statistics.median(risks), 1),
        "p05":    round(sorted(risks)[int(0.05 * n)], 1),
        "p95":    round(sorted(risks)[int(0.95 * n)], 1),
    }


# === Off-chain values are constant across all dates ===
off_chain_values = {k: off_chain[k] for k in OFF_CHAIN_SPEC}

# === Build per-date reports ===
reports = []

# Pre-launch: only off-chain available
score, off_dev, _ = deterministic_score(off_chain_values)
reports.append({
    "date": "pre-launch",
    "phase": "before launch",
    "risk_score": score,
    "risk_band":  monte_carlo_score(off_chain_values),
    "off_chain_deviation": round(off_dev, 3),
    "on_chain_deviation": None,
    "skipped_metrics": list(ON_CHAIN_SPEC.keys()),
})

launch_price = float(snapshots[0]["price"])

# Track previous snapshot to compute true holder deltas between observations
prev_holders = None
prev_age = None

for snap in snapshots:
    age_days = int(snap["age_days"])
    holder_count = int(snap["holder_count"])

    # price_drop only becomes a meaningful signal once at least one day has passed
    if age_days >= 1:
        price_drop = max(0.0, 1 - float(snap["price"]) / launch_price)
    else:
        price_drop = None  # not yet measurable; will be skipped + renormalized

    # Holders gained per day since the previous snapshot (true delta).
    # On the first snapshot, fall back to cumulative-since-launch
    # (with age=0 clamped to 1 so launch-day floods still register).
    # Negative deltas (holders exiting) are clamped to 0 — that registers
    # as 'no growth', and the price_drop metric carries the exit signal.
    if prev_holders is not None and age_days > prev_age:
        holder_growth_rate = max(0, holder_count - prev_holders) / (age_days - prev_age)
    else:
        holder_growth_rate = holder_count / max(age_days, 1)

    prev_holders, prev_age = holder_count, age_days

    on_values = {
        "top10_pct":          float(snap["top10_pct"]),
        "top50_pct":          float(snap["top50_pct"]),
        "holder_count":       holder_count,
        "holder_growth_rate": holder_growth_rate,
        "price_drop":         price_drop,
    }

    score, off_dev, on_dev = deterministic_score(off_chain_values, on_values)
    skipped = [k for k, v in on_values.items() if v is None]

    reports.append({
        "date": snap["snapshot_date"],
        "phase": snap["notes"].strip(),
        "risk_score": score,
        "risk_band":  monte_carlo_score(off_chain_values, on_values),
        "off_chain_deviation": round(off_dev, 3),
        "on_chain_deviation":  round(on_dev, 3),
        "on_chain_metrics": {
            k: (round(v, 4) if v is not None else None) for k, v in on_values.items()
        },
        "skipped_metrics": skipped,
    })

final = {
    "token":   snapshots[0]["name"],
    "address": snapshots[0]["addr"],
    "methodology": (
        "Each metric is normalized to a [0,1] deviation from an 'ideal token' baseline "
        "toward a worst-case value. Metrics may use a non-linear curve where appropriate "
        "(e.g. price_drop is concave with curve=0.5, so a 40% crash already scores ~0.7 "
        "rather than 0.5, reflecting that moderate drops are themselves strong signals). "
        "Per-metric deviations are weighted-averaged within the off-chain and on-chain "
        "blocks, the two blocks are combined (40/60), and the result is mapped through a "
        "sigmoid (k=10, x0=0.35) to a 0-100 risk score; the inflection at 0.35 reflects "
        "the prior that scanned tokens skew risky, so moderate deviations land in the "
        "60s rather than the 50s. The on-chain block tracks both holder_count (catches "
        "lack of organic adoption) and holder_growth_rate (catches sybil-inflated "
        "adoption from bot wallets). holder_growth_rate is computed as the per-day delta "
        "in holders between consecutive snapshots, so it measures genuine onboarding "
        "velocity rather than a cumulative average; this lets the model distinguish "
        "'launch-day wallet flood', 'organic growth', and 'holders exiting' as separate "
        "signals. Metrics that cannot yet be meaningfully measured (e.g. price_drop on "
        "launch day) are skipped and the remaining weights are renormalized, so absent "
        "evidence does not get treated as positive evidence. A Monte Carlo pass with "
        "Gaussian noise on the inputs produces a 5th-95th percentile band to express "
        "the uncertainty."
    ),
    "explanation": off_chain["explanation"],
    "reports": reports,
}

print(json.dumps(final, indent=2, ensure_ascii=False))

with open("data/final_risk_output.json", "w", encoding="utf-8") as f:
    json.dump(final, f, indent=2, ensure_ascii=False)
