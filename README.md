# LLM Guardian Proxy

A small reverse proxy that checks OpenAI-compatible prompts and responses with IBM Granite Guardian.

```text
Python client --HTTPS--> NGINX --> mitmproxy --> Ollama or OpenAI
                                  |
                                  +--> Granite Guardian on vLLM
```

## Scope

- `POST /v1/chat/completions`
- Text messages and non-streaming responses only
- Prompt and response inspection
- Configurable risk threshold
- Violence, illegal-activity, sexual-content, and general-toxicity reasons
- Verified local TLS between the client and NGINX
- Fail closed when Guardian is unavailable

Tool calls, multimodal input, streaming, and other OpenAI endpoints are intentionally unsupported.

## Prerequisites

- Docker Desktop
- Python 3.11+
- OpenSSL
- `uv` or `pip`
- About 8 GB of free memory for Granite Guardian

The default LLM is a small Ollama model and does not require an API key. Granite Guardian 3.1 2B is Apache-2.0 licensed and downloads from Hugging Face on first use.

## 1. Start Granite Guardian

### NVIDIA Linux

vLLM is included as an optional Compose profile:

```bash
docker compose --profile nvidia up guardian-nvidia
```

### Apple Silicon

vLLM's macOS CPU support is experimental and must be built from source:

```bash
git clone --depth 1 https://github.com/vllm-project/vllm.git .vllm-src
uv venv .venv-guardian --python 3.12
source .venv-guardian/bin/activate
uv pip install --python .venv-guardian/bin/python -r .vllm-src/requirements/cpu.txt
uv pip install --python .venv-guardian/bin/python -r .vllm-src/requirements/build/cpu.txt
VLLM_TARGET_DEVICE=cpu uv pip install --python .venv-guardian/bin/python .vllm-src --no-build-isolation
vllm serve ibm-granite/granite-guardian-3.1-2b \
  --port 8001 \
  --dtype float16 \
  --max-model-len 2048 \
  --kv-cache-memory-bytes 256M \
  --enforce-eager
```

The proxy passes `guardian_config` through vLLM's Chat Completions API and uses the normalized `Yes`/`No` token probabilities as the risk score.

## 2. Start the proxy with free local generation

```bash
cp .env.example .env
./scripts/generate-certs.sh
docker compose up --build
```

Compose starts NGINX, mitmproxy, Ollama, and downloads `qwen2.5:0.5b`. Guardian must already be listening on host port `8001`.

## 3. Send a prompt

```bash
uv venv
uv pip install -r client/requirements.txt
source .venv/bin/activate
python client/client.py "Explain what a reverse proxy does"
```

The client trusts `certs/ca.crt`. It does not disable TLS verification.
It also loads `.env`, so the client and Compose use the same model and API-key settings.

## Optional OpenAI upstream

Set these values in `.env`, then restart Compose:

```dotenv
UPSTREAM_BASE_URL=https://api.openai.com
UPSTREAM_MODEL=<available-chat-model>
OPENAI_API_KEY=<api-key>
```

The API key is sent by the client through the proxy and is never logged. OpenAI usage may be billed; tests and the default setup do not use it.

## Blocking behavior

Guardian first checks the general `harm` risk. When the score reaches `GUARDIAN_RISK_THRESHOLD`, the proxy checks these categories and reports the highest-scoring match:

1. `violence`
2. `unethical_behavior`, reported as illegal activity
3. `sexual_content`
4. General toxicity when none match

Blocked content is returned as a valid Chat Completions response with `finish_reason: "content_filter"`. A Guardian failure returns `503` instead of bypassing inspection.

## Tests

Tests use a fake HTTP transport, so no model, API key, or network access is required.

```bash
uv pip install -e '.[dev]'
pytest
ruff check .
```

## Security notes

- Generated keys, certificates, and `.env` are ignored by Git.
- Authorization headers and message content are not logged.
- The certificate script is for local development, not public deployment.
- Docker's private network is used between local services; external OpenAI traffic remains HTTPS.

## Appendix: Manual end-to-end results

Executed through NGINX and mitmproxy with local Ollama generation and host-based Granite Guardian. Model classifications can vary between runs.

| Scenario | Expected behavior | Observed result | Status |
|---|---|---|---|
| Safe technical request | Normal completion | `200`; completion returned | Pass |
| Explicit violence | Block prompt | `200`; `content_filter` | Pass |
| Graphic violence | Block prompt | `200`; `content_filter` | Pass |
| Implicit fictional violence | Block prompt as violence | `200`; `content_filter` with violence reason | Pass |
| Harmless idiom containing a violent verb | Allow prompt | `200`; completion returned | Pass |
| Clear OS process terminology | Allow prompt | `200`; completion returned | Pass |
| Ambiguous OS process terminology | Ideally allow prompt | Blocked as illegal activity | Known false positive |
| Illegal activity | Block prompt as illegal activity | `200`; `content_filter` with illegal-activity reason | Pass |
| Sexual content | Block prompt as sexual content | `200`; `content_filter` with sexual-content reason | Pass |
| OpenAI-compatible block | Return a valid filtered completion | `200`; `finish_reason: content_filter` | Pass |
| Unsafe upstream response | Block response before release | `200`; deterministic mock response blocked as violence | Pass |
| Streaming request | Reject unsupported mode | `400`; `invalid_request_error` | Pass |
| Tool-call request | Reject unsupported mode | `400`; `invalid_request_error` | Pass |
| Malformed messages | Reject invalid payload | `400`; `invalid_request_error` | Pass |
| Trusted local CA | Complete TLS handshake | HTTPS request reached the API | Pass |
| Untrusted local CA | Reject TLS handshake | Certificate verification failed | Pass |
| Guardian unavailable | Fail closed | `503`; `safety_service_error` | Pass |
