"""Lossless private center identifier for a Bot principal's u0 read."""
import base64
import re


def build_center_virtual_user_id(principal: str) -> str:
    if not isinstance(principal, str) or not re.fullmatch(r"(?:[0-9]{1,128}|onebot_v11:[0-9]{1,128}|qq_official:[A-Za-z0-9_-]{1,128})", principal):
        raise ValueError("Invalid Bot principal")
    return "u0v1_" + base64.urlsafe_b64encode(principal.encode()).decode().rstrip("=")
