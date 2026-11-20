# Offline task units

Use the standalone release process in the root README. The updater keeps its
09:42 schedule, OSS targets, timeouts and existing Viewer title-relation producer.
Backup timing, labels and output remain unchanged. Both execute installed modules
through /opt/taiko-bot/current; the production data root stays /home/sigaer/taiko.

The daily updater now resolves song/official-title IDs in the Viewer relation
file and publishes complete, unambiguous associations through the existing
local-title management API. Existing manual associations/conditions are retained;
new rows match by normalized title name and plate, never by official row ID.
The private API login config is `/home/sigaer/taiko/data/title_sync.json` (mode 600),
using the example in the Viewer repository's `deploy/title-sync.example.json`.
Missing credentials, API failures or failed read-back verification fail the job.
The updater never retries a write with an unknown outcome; a fresh rerun first
loads the latest catalog and applies only missing associations.

For title-only maintenance, run the installed
`python -I -m taiko_bot.offline.title_update --cached` under the existing bounded
QA runner; it generates relations and previews changes. Add `--apply` to publish.
The regular daily task refreshes the official catalog before generating/publishing.
