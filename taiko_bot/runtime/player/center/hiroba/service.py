from __future__ import annotations


import os

from typing import Tuple

from .client import HirobaClient, HirobaError

from .credentials import load_hiroba_credentials

HIROBA_SERVICE_TAIKO_NO = str(
    os.getenv("HIROBA_SERVICE_TAIKO_NO", "862074224984")
).strip()

def load_hiroba_service_credentials() -> Tuple[str, str]:
    creds = load_hiroba_credentials(HIROBA_SERVICE_TAIKO_NO)
    if creds is None:
        raise HirobaError(
            f"未配置 Hiroba 服务账号 {HIROBA_SERVICE_TAIKO_NO} 的登录凭据。"
        )
    return creds

def login_hiroba_service_client(*, timeout: int = 30) -> HirobaClient:
    email, password = load_hiroba_service_credentials()
    client = HirobaClient(timeout=timeout)
    client.login(email, password, taiko_no=HIROBA_SERVICE_TAIKO_NO)
    return client
