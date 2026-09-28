"""mitmproxy add-on that checks prompts and model responses with Granite Guardian."""

from __future__ import annotations

import json
import logging
import os

from mitmproxy import http

from guardian import Assessment, GuardianClient, GuardianUnavailable
from policy import (
    UnsupportedRequest,
    blocked_text,
    chat_completion,
    error_body,
    extract_request_content,
    extract_response_text,
)


LOG = logging.getLogger("guardian-proxy")


class GuardianProxy:
    def __init__(self) -> None:
        self.guardian = GuardianClient(
            base_url=os.environ["GUARDIAN_BASE_URL"],
            model=os.environ["GUARDIAN_MODEL"],
            api_key=os.getenv("GUARDIAN_API_KEY", "unused"),
            threshold=float(os.getenv("GUARDIAN_RISK_THRESHOLD", "0.5")),
            timeout=float(os.getenv("GUARDIAN_TIMEOUT_SECONDS", "30")),
        )

    async def request(self, flow: http.HTTPFlow) -> None:
        if flow.request.path.split("?", 1)[0] != "/v1/chat/completions":
            flow.response = self._error(404, "Only POST /v1/chat/completions is supported")
            return
        if flow.request.method != "POST":
            flow.response = self._error(405, "Only POST is supported")
            return

        try:
            payload = json.loads(flow.request.get_text(strict=True))
            if not isinstance(payload, dict):
                raise UnsupportedRequest("Request body must be a JSON object")
            content = extract_request_content(payload)
            assessment = await self.guardian.assess(content.user_text)
        except (json.JSONDecodeError, UnicodeDecodeError, UnsupportedRequest) as exc:
            flow.response = self._error(400, str(exc))
            return
        except GuardianUnavailable as exc:
            LOG.error("Guardian unavailable: %s", exc)
            flow.response = self._error(503, "Safety service unavailable", "safety_service_error")
            return

        flow.metadata["guardian_user_text"] = content.user_text
        if assessment.risk_score >= self.guardian.threshold:
            LOG.info(
                "Blocked prompt category=%s score=%.3f", assessment.category, assessment.risk_score
            )
            flow.metadata["guardian_blocked"] = True
            flow.response = self._blocked(
                "prompt", assessment, payload.get("model", "guardian-proxy")
            )

    async def response(self, flow: http.HTTPFlow) -> None:
        if (
            flow.response is None
            or "guardian_user_text" not in flow.metadata
            or flow.metadata.get("guardian_blocked")
        ):
            return
        if flow.response.status_code >= 400:
            return

        try:
            payload = json.loads(flow.response.get_text(strict=True))
            response_text = extract_response_text(payload)
            if response_text is None:
                return
            assessment = await self.guardian.assess(
                flow.metadata["guardian_user_text"], response_text
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            flow.response = self._error(
                502, "Upstream returned an invalid response", "upstream_error"
            )
            return
        except GuardianUnavailable as exc:
            LOG.error("Guardian unavailable: %s", exc)
            flow.response = self._error(503, "Safety service unavailable", "safety_service_error")
            return

        if assessment.risk_score >= self.guardian.threshold:
            LOG.info(
                "Blocked response category=%s score=%.3f",
                assessment.category,
                assessment.risk_score,
            )
            flow.response = self._blocked(
                "response", assessment, payload.get("model", "guardian-proxy")
            )

    async def done(self) -> None:
        await self.guardian.close()

    @staticmethod
    def _blocked(subject: str, assessment: Assessment, model: str) -> http.Response:
        return http.Response.make(
            200,
            chat_completion(blocked_text(subject, assessment.category), model),
            {"Content-Type": "application/json"},
        )

    @staticmethod
    def _error(
        status: int, message: str, error_type: str = "invalid_request_error"
    ) -> http.Response:
        return http.Response.make(
            status,
            error_body(message, error_type),
            {"Content-Type": "application/json"},
        )


addons = [GuardianProxy()]
