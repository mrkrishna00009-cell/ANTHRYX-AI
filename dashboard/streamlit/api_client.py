"""HTTP client for the FastAPI backend.

The dashboard deliberately holds no SQLAlchemy session and imports no
models. Every read and write goes through the same API the field PWA uses,
so authorization is enforced in exactly one place: the backend.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests

DEFAULT_BASE_URL = os.getenv("ANTHRYX_API_BASE_URL", "http://localhost:8000")
DEFAULT_TIMEOUT = float(os.getenv("ANTHRYX_API_TIMEOUT", "10"))


class ApiError(RuntimeError):
    """Raised when the backend is unreachable or returns an error status."""


@dataclass
class ApiClient:
    base_url: str = DEFAULT_BASE_URL
    timeout: float = DEFAULT_TIMEOUT
    token: str | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def get(self, path: str, **params: Any) -> Any:
        url = f"{self.base_url.rstrip('/')}{path}"
        try:
            response = requests.get(
                url, headers=self._headers(), params=params or None, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise ApiError(f"Cannot reach the backend at {url}: {exc}") from exc
        if response.status_code >= 400:
            raise ApiError(f"{response.status_code} from {path}: {response.text[:200]}")
        return response.json()

    def post(self, path: str, payload: dict | None = None, params: dict | None = None) -> Any:
        url = f"{self.base_url.rstrip('/')}{path}"
        try:
            response = requests.post(
                url, headers=self._headers(), json=payload if payload is not None else None,
                params=params, timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ApiError(f"Cannot reach the backend at {url}: {exc}") from exc
        if response.status_code >= 400:
            raise ApiError(f"{response.status_code} from {path}: {response.text[:300]}")
        return response.json()

    def post_file(self, path: str, *, params: dict | None = None,
                  files: dict | None = None) -> Any:
        """Multipart upload - used by OCR extraction and the voice endpoint."""
        url = f"{self.base_url.rstrip('/')}{path}"
        try:
            response = requests.post(
                url, headers=self._headers(), params=params, files=files, timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ApiError(f"Cannot reach the backend at {url}: {exc}") from exc
        if response.status_code >= 400:
            raise ApiError(f"{response.status_code} from {path}: {response.text[:300]}")
        return response.json()

    def login(self, email: str, password: str) -> dict:
        result = self.post("/api/v1/auth/login", {"email": email, "password": password})
        self.token = result["access_token"]
        return result

    def me(self) -> dict:
        return self.get("/api/v1/auth/me")

    def health(self) -> dict:
        return self.get("/api/v1/health")
