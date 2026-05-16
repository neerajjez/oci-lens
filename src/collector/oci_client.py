from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable, TypeVar

import oci
from oci.exceptions import RequestException, ServiceError

from src.utils.logger import get_logger

log = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # seconds
_OCI_TIMEOUT = (30, 120)  # (connect_s, read_s)


def _is_retryable(exc: ServiceError) -> bool:
    return exc.status == 429 or exc.status >= 500


def with_retry(fn: F) -> F:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return fn(*args, **kwargs)
            except ServiceError as exc:
                if not _is_retryable(exc) or attempt == _MAX_RETRIES:
                    log.error(
                        "oci_api_error",
                        status=exc.status,
                        code=exc.code,
                        message=exc.message,
                        attempt=attempt,
                    )
                    raise
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                log.warning(
                    "oci_retryable_error",
                    status=exc.status,
                    attempt=attempt,
                    retry_in_seconds=delay,
                )
                time.sleep(delay)
            except RequestException as exc:
                if attempt == _MAX_RETRIES:
                    raise
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                log.warning(
                    "oci_network_error",
                    error=str(exc),
                    attempt=attempt,
                    retry_in_seconds=delay,
                )
                time.sleep(delay)
    return wrapper  # type: ignore[return-value]


def _try_instance_principal() -> oci.config.Config | None:
    try:
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        log.info("auth_method", method="instance_principal")
        return {"signer": signer}
    except Exception as exc:
        log.debug("instance_principal_unavailable", reason=str(exc))
        return None


def _load_config_file(config_path: str, profile: str) -> oci.config.Config:
    cfg = oci.config.from_file(file_location=config_path, profile_name=profile)
    oci.config.validate_config(cfg)
    log.info("auth_method", method="config_file", profile=profile)
    return cfg


def build_config(oci_config_path: str, oci_profile: str) -> tuple[dict, oci.auth.signers.InstancePrincipalsSecurityTokenSigner | None]:
    ip = _try_instance_principal()
    if ip is not None:
        return {}, ip["signer"]
    cfg = _load_config_file(oci_config_path, oci_profile)
    return cfg, None


class OciClientFactory:
    def __init__(self, oci_config_path: str, oci_profile: str) -> None:
        self._cfg, self._signer = build_config(oci_config_path, oci_profile)

    def _kwargs(self, region: str | None = None) -> dict:
        kw: dict = {}
        if self._signer is not None:
            kw["signer"] = self._signer
        else:
            kw["config"] = self._cfg
        if region:
            if self._signer is not None:
                kw["config"] = {"region": region}
            else:
                kw["config"] = {**self._cfg, "region": region}
        return kw

    def compute(self, region: str) -> oci.core.ComputeClient:
        return oci.core.ComputeClient(**self._kwargs(region), timeout=_OCI_TIMEOUT)

    def blockstorage(self, region: str) -> oci.core.BlockstorageClient:
        return oci.core.BlockstorageClient(**self._kwargs(region), timeout=_OCI_TIMEOUT)

    def monitoring(self, region: str) -> oci.monitoring.MonitoringClient:
        return oci.monitoring.MonitoringClient(**self._kwargs(region), timeout=_OCI_TIMEOUT)

    def usage_api(self, region: str) -> oci.usage_api.UsageapiClient:
        return oci.usage_api.UsageapiClient(**self._kwargs(region), timeout=_OCI_TIMEOUT)

    def object_storage(self, region: str) -> oci.object_storage.ObjectStorageClient:
        return oci.object_storage.ObjectStorageClient(**self._kwargs(region), timeout=_OCI_TIMEOUT)

    @property
    def _config(self) -> dict:
        return self._cfg
