# Offline task deployment templates

These files are owned by Taiko and were not installed or activated during migration.
Install taiko-bot 0.14.0 with the center extras and shared runtime_memory artifact into
the selected interpreter first. Keep `/home/sigaer/taiko` as the existing working/data
directory, including existing catalogs, cache, private configuration and credentials.
No runtime data relocation or regeneration is required.

The song updater still schedules at 09:42, retains its existing OSS targets and timeout
behavior, and invokes the existing Viewer title-relation producer at the original path.
That Viewer script is an explicit external dependency, not copied or modified here.
The backup cron now calls the installed module in the same virtual environment as the
updater; labels, summary, schedule and log destination remain unchanged. Review interpreter
installation before a separately authorized deployment. HDU/storage maintenance units
are not part of these templates.

For the center bot only, replace the `taiko_runtime_init` plugin entry with
`taiko_bot.runtime.center_startup`. Sakura's tracked pyproject already records this
future startup configuration. Do not run both startup plugins. The client startup and
its own public-data initialization remain unchanged.
