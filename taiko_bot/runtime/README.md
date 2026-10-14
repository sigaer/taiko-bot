# Taiko runtime ownership

This is maintained source inside the existing `taiko-bot` distribution.
`public` owns the nine public song commands; `player.entry` owns tinfo, taikorec and progress
matchers and dispatch. `player.center` owns native preparation, public
presentation inputs and delivery. `player.client` owns remote preparation
and the existing client score card. `player.authority` checks each private
send. Application receives data only.

Load both entries in the **existing** NoneBot driver; do not start a second
QQ/OneBot connection consumer. Host feature switches remain generic host
infrastructure. Do not import Sakura `plugins` from these modules.

Install the candidate using exactly one host extra: `taiko-bot[center]`
(Core 0.1.1) or `taiko-bot[client]` (Core 0.1.2); Contract stays 0.1.0.
The entry validates these exact versions. Application is pinned to 0.8.0.
`TAIKO_CENTER_ROOT` selects the center's existing data/resource root
(default `/home/sigaer/taiko`), and `TAIKO_USERDATA_DIR` retains its existing
override. Neither configuration copies or migrates user data.

The original `taiko_store` import namespace is shipped by this distribution.
Its implementation was moved without changing publication, locks, recovery
or native materialization. Remaining Sakura callers can import the same
storage namespace; there is no tinfo forwarding adapter in Sakura.

Public/tinfo/taikorec fixes belong here. Other legacy Sakura private commands remain
outside this cutover and must not receive new Taiko-specific implementations
there. Their ownership migration requires separate scope and acceptance.
