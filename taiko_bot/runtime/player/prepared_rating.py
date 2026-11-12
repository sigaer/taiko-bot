"""V1 reuse is valid only at the same algorithm, inputs and catalog revision."""
from pathlib import Path
import hashlib
import json
from taiko_bot.public_catalog_cache import revision


class PreparedV1Results(list):
    def __init__(self, results, profile, collapse, paths, source, user_id, records_digest):
        super().__init__(results)
        self.profile = profile
        self.collapse = collapse
        self.paths = paths
        self.source = source
        self.user_id = str(user_id)
        self.records_digest = records_digest


def _records_digest(records):
    return hashlib.sha256(json.dumps(records,sort_keys=True,separators=(',', ':'),ensure_ascii=False).encode()).digest()


def prepare_v1_results(calculate, *, profile, collapse, song_path, user_id, records):
    paths = (str(Path('songs/rating_structured_with_ids.json').resolve()), str(Path(song_path).resolve()))
    before = tuple(revision(path) for path in paths)
    digest = _records_digest(records)
    results = calculate()
    after = tuple(revision(path) for path in paths)
    return PreparedV1Results(results, profile, collapse, paths, after if before == after else None, user_id, digest)


def reusable_v1_results(results, *, profile, collapse, user_id, records):
    return (isinstance(results, PreparedV1Results) and results.profile == profile
            and results.collapse == collapse and results.source is not None
            and results.user_id == str(user_id) and results.records_digest == _records_digest(records)
            and results.source == tuple(revision(path) for path in results.paths))
