"""Private local request proof: live credential plus exact owned binding or
explicit per-token service policy. Quota and asserted HTTP identity are not grants.
"""
import json
import re
from dataclasses import dataclass
from taiko_store import PublicationError

@dataclass
class SourceAuthorityError(PublicationError):
    status: int
    code: str

def denied():
    raise SourceAuthorityError(403, "denied")

def validate_source_actor(value):
    if not isinstance(value, dict) or value.get("kind") not in {"session", "developer"} or type(value.get("userId")) is not int or not 0 < value["userId"] <= 2**53-1 or not isinstance(value.get("credential"), str) or not re.fullmatch(r"[a-f0-9]{64}", value["credential"]):
        raise SourceAuthorityError(400, "invalid_request")
    if value["kind"] == "developer" and (not isinstance(value.get("tokenId"), str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value["tokenId"])):
        raise SourceAuthorityError(400, "invalid_request")
    return dict(value)

def require_legacy_developer_grant(cursor, actor, grant, *, lock=False):
    """Reprove the legacy Bot credential; v1 ResourceGrants are unrelated."""
    if actor["kind"] != "developer" or set(grant) != {"kind", "applicationId"}:
        denied()
    cursor.execute("""SELECT CAST(app.id AS CHAR) FROM web_developer_tokens t
        JOIN web_developer_applications app ON app.id=t.application_id AND app.user_id=t.user_id
        JOIN web_user_accounts a ON a.id=t.user_id
        WHERE t.id=%s AND t.user_id=%s AND t.token_hash=%s AND t.status='active'
        AND t.revoked_at IS NULL AND app.status='approved' AND a.email_verified=1"""
        + (" FOR UPDATE" if lock else ""), (actor["tokenId"], actor["userId"], actor["credential"]))
    if cursor.fetchone() != (grant["applicationId"],):
        denied()


def require_source_authority(cursor, actor, grant, source, scope, *, lock=False):
    suffix = " FOR UPDATE" if lock else ""
    cursor.execute("SELECT id FROM web_user_accounts WHERE id=%s"+suffix, (actor["userId"],))
    row = cursor.fetchone()
    if row is None or row[0] != actor["userId"]:
        raise SourceAuthorityError(401, "unauthorized")
    if actor["kind"] == "session":
        cursor.execute("SELECT user_id FROM web_user_sessions WHERE session_token=%s AND expires_at>NOW()"+suffix, (actor["credential"],))
        valid = cursor.fetchone()
        if valid is None or valid[0] != actor["userId"]:
            raise SourceAuthorityError(401, "unauthorized")
    else:
        cursor.execute("SELECT CAST(id AS CHAR),user_id FROM web_developer_tokens WHERE id=%s AND token_hash=%s AND status='active' AND revoked_at IS NULL"+suffix, (actor["tokenId"], actor["credential"]))
        valid = cursor.fetchone()
        if valid != (actor["tokenId"], actor["userId"]):
            raise SourceAuthorityError(401, "unauthorized")
    if not isinstance(grant, dict):
        denied()
    if grant.get("kind") == "developer":
        require_legacy_developer_grant(cursor, actor, grant, lock=lock)
    elif grant.get("kind") == "owner":
        expected = grant.get("binding")
        if not isinstance(expected, dict) or expected.get("taiko_id") != source or expected.get("source") != ("wahlap" if scope == "wahlap_update" else "hiroba") or expected.get("manual_account_id"):
            denied()
        cursor.execute("SELECT CAST(id AS CHAR),taiko_id,source,manual_account_id FROM web_taiko_bindings WHERE user_id=%s AND CAST(taiko_id AS BINARY)=CAST(%s AS BINARY) ORDER BY id LIMIT 2"+suffix, (actor["userId"], source))
        rows = cursor.fetchall()
        if len(rows) != 1 or tuple(rows[0]) != (str(expected.get("id")), source, expected["source"], None):
            denied()
    elif grant.get("kind") == "service" and actor["kind"] == "developer":
        cursor.execute("SELECT CAST(id AS CHAR),developer_user_id,service_name,scopes_json,sources_json,revision_nonce,status,DATE_FORMAT(expires_at,'%%Y-%%m-%%dT%%H:%%i:%%s'),issued_by_user_id FROM taiko_source_service_grants WHERE developer_token_id=%s AND status='active' AND (expires_at IS NULL OR expires_at>NOW())"+suffix, (actor["tokenId"],))
        row = cursor.fetchone()
        if row is None or list(row) != grant.get("tuple") or row[1] != actor["userId"] or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", row[2]) or not re.fullmatch(r"[a-f0-9]{32}", row[5]):
            denied()
        scopes, sources = json.loads(row[3]), json.loads(row[4])
        if not isinstance(scopes, list) or scope not in scopes or (sources != "*" and (not isinstance(sources, list) or source not in sources)):
            denied()
    else:
        denied()
