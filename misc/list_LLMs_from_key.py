# print out all LLMs avaiable for a given key, to use in the off-chain analysis
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
for m in client.models.list().data:
    print(m.id)
