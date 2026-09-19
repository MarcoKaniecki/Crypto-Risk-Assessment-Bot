# Crypto Risk Bot (Lumen)

A risk-scoring tool for low-cap tokens. Lumen combines **off-chain** signals (promotion patterns, public sentiment, disclosure quality) with **on-chain** signals (holder concentration, holder dynamics, price drop) to flag tokens that look like prior rugs — ideally *before* a retail buyer commits money.

For the full motivation, methodology, and case study, see the accompanying report.

---

## How It Works

The pipeline runs in two parallel branches that meet at a final scoring step.

**Off-chain branch (LLM-based, two-pass).** One LLM call per source scores each on hype, influencer credibility, red-flag density, and disclosure quality, and returns a short rationale. A second call summarizes the per-source rationales into one explanation. This branch can run *before* launch, since it depends only on text.

**On-chain branch (statistical).** For a target token and a list of snapshot dates, the pipeline pulls the full holder list from GoldRush at each historical block, excludes the LP, the token contract, and known burn addresses, and computes concentration metrics from the remaining wallets. This branch only activates *at launch and after*.

**Risk score.** Each branch produces a feature vector. The final score is computed as a weighted deviation from an "ideal token" reference point, then mapped through a sigmoid to a bounded score in $[0, 1]$.

---

## Setup

### Requirements

- Python 3.10+
- A [GoldRush (Covalent)](https://goldrush.dev/) API key for on-chain data
- An OpenAI API key (or compatible LLM provider) for the off-chain branch

### Install

```bash
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
pip install -r requirements.txt
```

### Configure API keys
Create a .env file in the project root:

```env
GOLDRUSH_API_KEY=your_goldrush_key_here
OPENAI_API_KEY=your_openai_key_here
```

A 2-week free trial GoldRush key can be acquired from https://goldrush.dev/.

## Run

Each stage is run separately. The three scripts are independent — they read and write files in `data/`, and you run them in order.

### 1. Score the off-chain branch

```bash
python3 off-chain.py
```
Program will take 10-15 seconds to finish.

Reads `data/off-chain_input.json` (the curated dataset of public sources about the target token) and writes the averaged metrics and summary explanation to `data/off-chain_output.json`.

### 2. Pull the on-chain snapshots

```bash
python3 on-chain.py
```

Fetches the holder list from GoldRush at each configured snapshot block, excludes the LP, the token contract, and known burn addresses, and prints the per-snapshot concentration metrics to the terminal. The token address, pair address, and snapshot schedule are configured at the bottom of `on-chain.py`.

The output of this script was sorted manually and copy-pasted into `data/on-chain_output.csv`, which is the file the next stage reads. Writing the CSV directly from the script would be a small addition, but the run we used for this project predates that change.

### 3. Compute the final risk score

```bash
python3 risk_score.py
```

Reads `data/off-chain_output.json` and `data/on-chain_output.csv`, computes the per-snapshot deviation from the ideal-token baseline, runs the Monte Carlo uncertainty pass, and writes the final report to `data/final_risk_output.json`.

---

## Data files

All inputs and outputs live in `data/`:

- **`off-chain_input.json`** — manually curated dataset of public sources (forum threads, influencer activity, project disclosures) about the target token, in the schema used by the included KIDS example.
- **`off-chain_output.json`** — the four averaged off-chain metrics (hype level, influencer credibility, red-flag density, disclosure quality) plus a natural-language summary explanation.
- **`on-chain_output.csv`** — per-snapshot on-chain metrics (top-10 and top-50 supply share, holder count, price, age in days) for each block sampled.
- **`final_risk_output.json`** — the final report: a pre-launch risk score from the off-chain branch alone, plus one combined score per on-chain snapshot, each with a Monte Carlo 5th-95th percentile band and the underlying metrics.

