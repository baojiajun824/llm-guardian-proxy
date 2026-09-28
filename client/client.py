"""Send one prompt through the TLS-protected safety proxy."""

from __future__ import annotations

import argparse
import os

import httpx
from openai import OpenAI
from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", help="Prompt to send")
    args = parser.parse_args()

    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY", "ollama"),
        base_url=os.getenv("PROXY_BASE_URL", "https://localhost:8443/v1"),
        http_client=httpx.Client(
            verify=os.getenv("CA_CERT", "certs/ca.crt"),
            trust_env=False,
        ),
    )
    response = client.chat.completions.create(
        model=os.getenv("UPSTREAM_MODEL", "qwen2.5:0.5b"),
        messages=[{"role": "user", "content": args.prompt}],
        stream=False,
        max_tokens=200,
    )
    print(response.choices[0].message.content)


if __name__ == "__main__":
    main()
