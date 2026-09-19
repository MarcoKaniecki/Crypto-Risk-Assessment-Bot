import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()  # reads .env (keys) into environment variables

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

with open("data/off-chain_input.json", "r", encoding="utf-8") as f:
    data = json.load(f)

# Define metrics in one place so the prompt and the averaging stay in sync
METRICS = [
    "hype_level",
    "influencer_credibility",
    "red_flag_density",
    "disclosure_quality",
]

per_source = []

# Step 1: score each source
print("processing sources...")
for source in data["sources"]:
    response = client.chat.completions.create(
        model="gpt-5.2",
        messages=[
            {"role": "system", "content": (
                "You are a forensic crypto-fraud analyst. Read the source and respond ONLY with valid JSON "
                "containing five fields:\n"
                "  hype_level: integer 1-10 (how much promotional / FOMO-driven activity this source "
                "describes or exhibits around the token, regardless of the source's own tone)\n"
                "  influencer_credibility: integer 1-10 (10 = highly credible promoters, "
                "1 = known scam promoters)\n"
                "  red_flag_density: integer 1-10 (how many fraud indicators are present: insider wallets, "
                "no audit, no liquidity lock, anti-whale bypass, etc.)\n"
                "  disclosure_quality: integer 1-10 (10 = paid promotions, financial relationships, and team "
                "allocations are clearly disclosed; 1 = undisclosed paid shilling, hidden conflicts of interest)\n"
                "  rationale: 1-2 sentences explaining why you assigned these scores"
            )},
            {"role": "user", "content": json.dumps(source, ensure_ascii=False)}
        ],
        temperature=0.2,
        response_format={"type": "json_object"}
    )
    per_source.append(json.loads(response.choices[0].message.content))

# Step 2: average all numeric metrics
n = len(per_source)
averages = {
    metric: round(sum(s[metric] for s in per_source) / n, 1)
    for metric in METRICS
}

# Step 3: ask the model to write one combined explanation from the per-source rationales
print("summarizing explanations...")
summary_response = client.chat.completions.create(
    model="gpt-5.2",
    messages=[
        {"role": "system", "content": (
            "You are a forensic crypto-fraud analyst. Given the per-source rationales below, "
            "write a single 2-3 sentence summary explaining the overall picture across all sources."
        )},
        {"role": "user", "content": json.dumps([s["rationale"] for s in per_source], ensure_ascii=False)}
    ],
    temperature=0.7
)
overall_explanation = summary_response.choices[0].message.content

# Final result
final = {
    **averages,
    "explanation": overall_explanation
}

print(json.dumps(final, indent=2, ensure_ascii=False))
