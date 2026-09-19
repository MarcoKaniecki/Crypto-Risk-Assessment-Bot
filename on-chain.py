import requests
import os
from decimal import Decimal
from dotenv import load_dotenv

load_dotenv()  # reads .env (keys) into environment variables

API_KEY = os.getenv("GOLDRUSH_API_KEY")

BURN_ADDRESSES = {
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dead",
    "0x0000000000000000000000000000000000000001",
}


# Goldrush.dev documentation
# https://goldrush.dev/docs/api-reference/foundational-api/balances/get-token-holders-as-of-any-block-height-v2
def _paginate_holders(chain_id, address, block):
    """Yield all holder items for a token at a block."""
    url = f"https://api.covalenthq.com/v1/{chain_id}/tokens/{address}/token_holders_v2/"
    page = 0
    while True:
        r = requests.get(
            url,
            params={"block-height": block, "page-size": 1000, "page-number": page},
            auth=(API_KEY, ""),
            timeout=60,
        )
        data = r.json().get("data") or {}
        items = data.get("items") or []
        if not items:
            return
        for h in items:
            yield h
        if not (data.get("pagination") or {}).get("has_more"):
            return
        page += 1


# Computes per-snapshot holder concentration metrics from the paginated
# token_holders_v2 endpoint above. observed_total is summed from the page
# items rather than passed in, so this works for any token without needing
# to know the on-chain total supply ahead of time.
def get_onchain_features(chain_id, token, pair, block):
    """
    Returns:
      lp_pct        -> trading pair's share of total supply
      top10_ex_pct  -> top-10 non-excluded share
      top50_ex_pct  -> top-50 non-excluded share
      holder_count  -> non-excluded holder count
    Excluded = LP pair, token contract, burn addresses.
    """
    excluded = {a.lower() for a in BURN_ADDRESSES} | {pair.lower(), token.lower()}

    pair_l = pair.lower()
    pair_bal = Decimal(0)
    balances = []
    observed_total = Decimal(0)
    for h in _paginate_holders(chain_id, token, block):
        bal = Decimal(h["balance"])
        observed_total += bal
        if h["address"].lower() == pair_l:
            pair_bal = bal
        if h["address"].lower() in excluded:
            continue
        balances.append(bal)
    balances.sort(reverse=True)

    if not observed_total:
        return {"lp_pct": 0.0, "top10_ex_pct": 0.0, "top50_ex_pct": 0.0, "holder_count": 0}

    top10 = sum(balances[:10])
    top50 = sum(balances[:50])

    return {
        "lp_pct":       float(pair_bal / observed_total),
        "top10_ex_pct": float(top10 / observed_total),
        "top50_ex_pct": float(top50 / observed_total),
        "holder_count": len(balances),
    }


def run_timeseries(chain_id, token, pair, snapshots):
    """
    snapshots: list of dicts with keys:
      label, date, block, price_high
    """
    rows = []
    for s in snapshots:
        print(f"fetching {s['date']} (block {s['block']:,}) [{s['label']}] ... ",
              end="", flush=True)
        f = get_onchain_features(chain_id, token, pair, s["block"])
        f.update(s)
        rows.append(f)
        print("done")

    print()
    header = (f"{'date':<12}{'label':<16}{'lp_pct':>9}{'top10':>9}{'top50':>9}"
              f"{'holders':>10}{'price high USD':>16}")
    print(header)
    print("-" * len(header))
    for r in rows:
        print(f"{r['date']:<12}{r['label']:<16}"
              f"{r['lp_pct']:>9.4f}"
              f"{r['top10_ex_pct']:>9.4f}{r['top50_ex_pct']:>9.4f}"
              f"{r['holder_count']:>10,}"
              f"{r['price_high']:>12.6f}")
    return rows


if __name__ == "__main__":
    # SaveTheKids 2021, Jun 5 launch / Jun 6 rug pull
    # price high taken from dexscreener directly
    CHAIN_ID = 56
    TOKEN = "0x7acf49997e9598843cb9051389fa755969e551bb"   # KIDS
    PAIR  = "0xcaf3BA00f81bc325fdbf4f7A2f5dD963082B8b88"   # Pancakeswap V2 KIDS/WBNB

    rows = run_timeseries(
        chain_id=CHAIN_ID,
        token=TOKEN,
        pair=PAIR,
        snapshots=[
            {
                "label":      "launch+pump",
                "date":       "2021-06-05",
                "block":      8_045_603,
                "price_high": 0.02833,
            },
            {
                "label":      "dump",
                "date":       "2021-06-06",
                "block":      8_074_341,
                "price_high": 0.016,
            },
            {
                "label":      "post dump",
                "date":       "2021-06-07",
                "block":      8_103_100,
                "price_high": 0.0039,
            },
        ],
    )
