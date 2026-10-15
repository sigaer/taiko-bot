from ..authority import TinfoDenied, TinfoUnavailable, AuthorizedDelivery
"""Native tinfo preparation. No capability in this module crosses into Application.

Visibility deliberately follows the selected native binding, including u0.
The host alone owns SQL connections, materialization and publication leases.
"""
from contextlib import ExitStack
from dataclasses import asdict
from hashlib import sha256
import json
import time
from pathlib import Path

from taiko_application.private_input import (
    AuthorizedTarget, PreparedPrivateInput, Provenance, ReadFailure,
)
from taiko_store.publication import PublicationStore, PublicationError
from taiko_store.merged_read import MAX_BYTES, merge_rule_revision
from .bot_binding_authority import normalize_bot_principal
from .bot_binding_mutation import _read, _entry
from .materialization import materialize_merged_bind_userdata, MergedBindError






def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class TinfoHostProvider:
    def __init__(self, *, connection_factory, userdata_root):
        self._connection_factory = connection_factory
        self._root = Path(userdata_root)
        self._deadline = time.monotonic() + 120

    def _remaining(self):
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TinfoUnavailable()
        return min(remaining, 30)

    def _snapshot(self, actor, principal):
        self._remaining()
        actor, principal = normalize_bot_principal(actor), normalize_bot_principal(principal)
        connection = self._connection_factory()
        cursor = None
        try:
            cursor = connection.cursor()
            rows, virtual = _read(cursor, principal, locked=False)
            # Finish the read transaction before waiting for any file lease.
            connection.commit()
        finally:
            if cursor is not None:
                cursor.close()
            connection.close()
        if not rows:
            raise TinfoDenied(404)
        selected = next((row for row in rows if row.current), rows[0])
        if actor != principal and not selected.visible:
            raise TinfoDenied()
        observation = _digest({"rows": [asdict(row) for row in rows], "virtual": virtual})
        return rows, _entry(rows, virtual), observation

    def verify(self, prepared):
        target = prepared.authorized_target
        _, _, observation = self._snapshot(target.actor, target.principal)
        if observation != target.binding_observation:
            raise TinfoDenied()

    def verify_initial(self):
        actor, principal, observation = self._initial
        if self._snapshot(actor, principal)[2] != observation:
            raise TinfoDenied()

    def _store(self, identity, *, merged=False):
        options = {"lock_timeout": self._remaining()}
        if merged:
            options["max_file_bytes"] = MAX_BYTES
        return PublicationStore(self._root, identity, **options)

    def prepare(self, actor, principal, *, include_history=False, history_dan_id=None, b30_command=None, trend_command=None, summary_command=False):
        rows, entry, observation = self._snapshot(actor, principal)
        self._initial = (actor, principal, observation)
        virtual = entry["current_slot"] == 0
        ids = tuple(entry["ids"]) if virtual else (entry["ids"][entry["current_index"]],)
        profile = entry["ids"][entry["current_index"]]
        source = entry["sources"].get(profile) if not virtual else "wahlap"
        update = "更新hiroba" if source == "hiroba" else "taikoupdate"
        self.recommendation_missing_hint = f"您还未上传数据哦~请先发送“{update}”进行上传"
        # The two attempts cover materialize -> captured publication races.
        for attempt in range(2):
            if self._snapshot(actor, principal)[2] != observation:
                raise TinfoDenied()
            if virtual:
                materialized = materialize_merged_bind_userdata(principal, entry, userdata_dir=self._root)
                identity = materialized.virtual_user_id
            else:
                identity = ids[0]
            target = AuthorizedTarget(actor, principal, identity, ids, profile, observation)
            with ExitStack() as stack:
                expected = None
                if virtual:
                    publications = {}
                    for member in sorted(ids):
                        store = self._store(member, merged=True)
                        stack.enter_context(store.shared())
                        publications[member] = store.reader().publication
                    if any(value is None for value in publications.values()):
                        raise MergedBindError("合并账户数据暂不可用，请更新真实账号后重试。")
                    # Frozen native-u0-incremental-v1 read-side verification.
                    # No new recipe, receipt, publication or storage API.
                    expected = _digest({"recipe": "native-u0-incremental-v1", "principal": principal,
                        "members": [(member, publications[member]) for member in ids],
                        "profile": profile, "rule": merge_rule_revision()})
                store = self._store(identity, merged=virtual)
                stack.enter_context(store.shared())
                view = store.reader()
                if virtual and (view.manifest is None or view.manifest.get("dependencyHash") != expected):
                    continue  # ExitStack releases all leases before preparation retries.
                failure = None
                raw = b""
                try:
                    raw = view.current_raw()
                    current = json.loads(raw.decode("utf-8"))
                    if summary_command:
                        from datetime import datetime
                        self.summary_utime = str(datetime.fromtimestamp(round(view.file_times("current")["ctime"])))
                except Exception as error:
                    # Preserve tinfo's deferred renderer error priority. A query
                    # returning text does not start failing because current is absent.
                    current = None
                    failure = ReadFailure(isinstance(error, FileNotFoundError), "" if isinstance(error, FileNotFoundError) else str(error))
                history = None
                if include_history:
                    from .progress_support.dojo_score import build_dojo_score_map
                    history = []
                    # Dani needs only the newest matching dojo payload. Do not
                    # retain entire song-history datasets or scan when current wins.
                    current_dojo = (current or {}).get('dojo') or {}
                    needs_fallback = current is not None and history_dan_id and history_dan_id not in build_dojo_score_map(current_dojo)
                    if needs_fallback:
                        for name in sorted(view.history_names(), reverse=True):
                            self._remaining()
                            try:
                                payload = json.loads(view.history_raw(name).decode('utf-8'))
                            except (FileNotFoundError, UnicodeError, ValueError):
                                continue  # Frozen Dani skips unreadable JSON snapshots.
                            if not isinstance(payload, dict) or 'dojo' not in payload:
                                continue
                            dojo = payload.get('dojo') or {}
                            if history_dan_id in build_dojo_score_map(dojo):
                                history.append({'fileName': name, 'payload': {'dojo': dojo}})
                                break
                    history = tuple(history)
                if b30_command is not None:
                    from .b30_history import capture
                    try:
                        history = capture(self,view,store,b30_command,current)
                    except (TinfoDenied,TinfoUnavailable):
                        raise
                    except Exception as error:
                        # Preserve B30 Application error mapping at its render branch.
                        self.b30_preparation_error = error
                        history = ()
                if trend_command is not None:
                    from .trend_history import capture
                    history = capture(self, view, store, trend_command)
                publication = view.publication
                provenance = Provenance(
                    "native-publication" if publication else "native-legacy",
                    _digest(publication) if publication else sha256(raw).hexdigest(),
                    None, expected, ids, profile)
                if include_history or b30_command is not None or trend_command is not None:
                    from dataclasses import replace
                    observation_id = _digest({'current': provenance.current_view, 'history': history})
                    provenance = replace(provenance, current_view=observation_id, history_view=observation_id)
                prepared = PreparedPrivateInput(target, current, history, provenance, failure)
            self.verify(prepared)
            return prepared
        raise TinfoUnavailable()

    def prepare_b30(self, actor, principal, command):
        return self.prepare(actor,principal,b30_command=command)

    def prepare_trend(self, actor, principal, command):
        return self.prepare(actor, principal, trend_command=command)

    def prepare_display(self, actor, principal):
        private = self.prepare(actor, principal)
        from .display_prepare import prepare
        prepare(self, private)
        return private
