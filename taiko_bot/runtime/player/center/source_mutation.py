"""Granted local acquisition: Source EX -> SQL authority -> real writer.
No parent EX, public userid gateway or credentials in argv. File observations
remain committed after an unrelated late SQL/transport failure.
"""
import hashlib
import os
import re
import time
import stat
from pathlib import Path
from taiko_store import PublicationError, PublicationStore
from .viewer_source_authority import SourceAuthorityError, validate_source_actor, require_source_authority

class AuthorizedPublicationStore(PublicationStore):
    authorize = None
    def publish(self, *args, **kwargs):
        if self.authorize is None:
            raise PublicationError("Source grant not installed")
        self.authorize()
        return super().publish(*args, **kwargs)

def run_source_mutation(request, *, connection_factory, userdata_root, cache_root):
    if not isinstance(request, dict) or request.get("scope") not in {"wahlap_update", "hiroba_sync"} or not isinstance(request.get("source"), str) or not re.fullmatch(r"[0-9]{1,25}", request["source"]) or re.fullmatch(r"98[0-9]{16}", request["source"]) or not isinstance(request.get("operationId"), str) or not re.fullmatch(r"[a-f0-9]{32}", request["operationId"]):
        raise SourceAuthorityError(400, "invalid_request")
    actor = validate_source_actor(request.get("actor"))
    scope, identity, grant = request["scope"], request["source"], request.get("grant")
    for key, limit in (("email", 254), ("password", 1024)):
        if not isinstance(request.get(key), str) or len(request[key]) > limit:
            raise SourceAuthorityError(400, "invalid_request")
    if type(request.get("includeImage")) is not bool or type(request.get("showAll")) is not bool:
        raise SourceAuthorityError(400, "invalid_request")
    connection = connection_factory()
    try:
        with connection.cursor() as cursor:
            require_source_authority(cursor, actor, grant, identity, scope)
            connection.commit()
            store = AuthorizedPublicationStore(userdata_root, identity)
            with store.exclusive():
                connection.begin()
                proof = lambda: require_source_authority(cursor, actor, grant, identity, scope, lock=True)
                store.authorize = proof
                proof()
                if scope == "wahlap_update":
                    from taiko_bot.services.sync_dispatch_server import refresh_userdata_from_wahlap, read_local_userdata, write_local_snapshot
                    refresh_userdata_from_wahlap(identity, publication_store=store)
                    write_local_snapshot(identity, read_local_userdata(identity, publication_store=store).parsed, publication_store=store)
                else:
                    from .hiroba.credentials import decrypt_password
                    from .hiroba.sync import sync_hiroba_userdata
                    email, password = request["email"].strip(), request["password"].strip()
                    if not email or not password:
                        cursor.execute("SELECT email,password_enc FROM web_hiroba_credentials WHERE taiko_no=%s LIMIT 1", (identity,))
                        row = cursor.fetchone()
                        if row is None:
                            raise SourceAuthorityError(409, "hiroba_credentials_missing")
                        email, password = row[0], decrypt_password(row[1])
                    resolved = sync_hiroba_userdata(email, password, taiko_no=identity, publication_store=store)
                    if resolved != identity:
                        raise PublicationError("Source acquisition mismatch")
                proof()
                view = store.reader()
                publication = view.publication
                if publication is None:
                    raise PublicationError("Source publication missing")
                image_bytes, image_hash = 0, None
                if request["includeImage"]:
                    from .draw_dress import render_update_changes_image
                    image = render_update_changes_image(int(identity), show_all=request["showAll"], score_view=view)
                    if not isinstance(image, bytes) or not 0 < len(image) <= 16*1024**2:
                        raise PublicationError("Source image limit")
                    image_bytes, image_hash = len(image), hashlib.sha256(image).hexdigest()
                    directory = Path(cache_root)/"source-render"
                    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                    if directory.is_symlink() or directory.stat().st_mode & 0o077:
                        raise PublicationError("Source render directory invalid")
                    # Parent death can leave a private disposable artifact. Keep
                    # admission finite and remove only old owned nonce files.
                    retained = 0
                    for candidate in directory.iterdir():
                        if not re.fullmatch(r"[a-f0-9]{32}\.png", candidate.name):
                            continue
                        try:
                            info = candidate.lstat()
                        except FileNotFoundError:
                            continue
                        if not stat.S_ISREG(info.st_mode):
                            raise PublicationError("Source render entry invalid")
                        if time.time()-info.st_mtime > 1800:
                            candidate.unlink(missing_ok=True)
                        else:
                            retained += 1
                            if retained >= 16:
                                raise PublicationError("Source render capacity")
                    path = directory/(request["operationId"]+".png")
                    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
                    with os.fdopen(fd, "wb") as output:
                        output.write(image)
                    del image
                proof()
                store._require_lock(write=True)
                connection.commit()
                return {"operationId": request["operationId"], "source": identity, **publication, "imageBytes": image_bytes, "imageHash": image_hash}
    except Exception:
        try:
            connection.rollback()
        except Exception:
            connection.close()
        raise
    finally:
        connection.close()
