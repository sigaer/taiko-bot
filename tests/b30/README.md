# B30 ownership acceptance

`events.py` loads the installed player plugin, dispatches real OneBot/QQ events,
and compares independently sliced old handlers/renderers against the new runtime.
Only public assets and synthetic current/history/binding fixtures are used.
Socket/SQL/production-path audit guards remain active. During Application/rendering,
private reads, legacy provider imports and all file writes are rejected. Images
are compared by SHA256 and dimensions; paired exceptions never count as parity.

Run under the workspace memory QA wrapper, serially, with separate center/client
venvs and their pinned Core versions. `--baseline` is the frozen host source root
containing `plugins`, `--work` is an isolated fixture directory, `--assets` contains
only public templates/fonts, and `--application` is the Taiko repository root.
Set `PYTHON_MEMORY_RUNTIME_ROOT` to the isolated copy of the public memory runtime.

- Default: normal/u0, both adapters, v1/v2, summary, dimensions, radar and errors.
- `--edges`: N boundaries, wrapped/flag dimensions, rating version/default differences.
- `--history-only`: first/hot/changed/missing history, exact image comparison;
  center additionally compares named daily archives before/after new-day/current-day,
  immutable past-day and retention cases against the frozen implementation.
- `--faults`: no scores, low accuracy and unavailable public v2 datasets.
- `--mode security`: real Host authority, visibility, binding changes, revocation,
  transport failure and client mixed source views; real statistics recorder with
  only its queue intercepted.

`test_update_diff.py` moves the old Sakura B30 delta assertions to their owner.
Existing public/tinfo/recommendation/progress representative scripts and full-host
load checks validate the peripheral command registration and import chain.

Intentional fix: the former client table renderers cast native u0 source IDs to
integers. The new renderers retain the source ID. For those formerly failing cases,
require a successful image identical to the same captured ordinary-account payload.

`--native` verifies real center u0 first/hot/member/profile/current publication
preparation. `--archive` independently records exact daily durable-write counts
(first/new-today write once, hot/past/retention write zero), in addition to payloads.
The client now returns the original missing-current error text through the existing
Host authorization channel instead of allowing an uncaught provider exception.
