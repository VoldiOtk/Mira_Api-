import os
import json
import httpx
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"

async def main():
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
            if res.status_code == 200:
                data = res.json()
                valid_models = []
                for m in data.get("models", []):
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods:
                        valid_models.append(m["name"])
                
                with open("models.txt", "w") as f:
                    f.write("\n".join(valid_models))
                print("Models written to models.txt")
            else:
                print("Error:", res.text)
    except Exception as e:
        print("Exception:", e)

import asyncio
asyncio.run(main())
