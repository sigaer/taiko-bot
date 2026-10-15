from __future__ import annotations


import re

from .credentials import encrypt_password, decrypt_password, credential_request_fingerprint

class CredentialWorkerError(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.status, self.code = status, code

def run_private_credentials(request, *, discovery=None):
    if not isinstance(request, dict) or not isinstance(request.get("operationId"), str) or not re.fullmatch(r"[a-f0-9]{32}", request["operationId"]):
        raise CredentialWorkerError(400, "invalid_request")
    mode = request.get("mode")
    if mode == "decode":
        cipher = request.get("passwordEnc")
        if not isinstance(cipher, str) or not 1 <= len(cipher.encode("utf-8")) <= 8192:
            raise CredentialWorkerError(400, "invalid_request")
        decrypt_password(cipher)
        return {"operationId": request["operationId"], "hasCredentials": True}
    if mode not in {"fingerprint", "discover"}:
        raise CredentialWorkerError(400, "invalid_request")
    values = [request.get(key, "") for key in ("email", "password", "target", "principal")]
    if any(not isinstance(value, str) or value != value.strip() for value in values):
        raise CredentialWorkerError(400, "invalid_request")
    email, password, target, principal = values
    if not email or not password or len(email.encode("utf-8")) > 255 or len(password.encode("utf-8")) > 4096 or len(principal) > 191 or (target and not re.fullmatch(r"[0-9]{1,25}", target)):
        raise CredentialWorkerError(400, "invalid_request")
    fingerprint = credential_request_fingerprint(*values)
    result = {"operationId": request["operationId"], "intentHash": fingerprint}
    if mode == "fingerprint":
        return result
    if discovery is None:
        from .sync import discover_hiroba_playable_cards
        discovery = discover_hiroba_playable_cards
    try:
        cards = discovery(email, password)
    except Exception:
        raise CredentialWorkerError(502, "hiroba_login_failed") from None
    ids = []
    for index, card in enumerate(cards):
        if index >= 128:
            raise CredentialWorkerError(503, "credential_unavailable")
        identity = str(card.taiko_no or "").strip()
        if not identity:
            continue
        if not re.fullmatch(r"[0-9]{1,25}", identity) or re.fullmatch(r"98[0-9]{16}", identity):
            raise CredentialWorkerError(503, "credential_unavailable")
        if target and target != identity:
            continue
        if identity in ids:
            raise CredentialWorkerError(503, "credential_unavailable")
        ids.append(identity)
    result.update(taikoIds=ids, passwordEnc=encrypt_password(password))
    return result
