# Retired public song distribution

Phase 2F-E moves the nine public command implementations to
`taiko_bot.runtime.public` in the existing `taiko-bot` distribution.
This directory now contains historical parity tests and provenance only;
it is not a buildable or independently maintained plugin product.

The isolated cutover candidates load `taiko_bot.runtime.public` and
`taiko_bot.runtime.player.entry` in each host's existing NoneBot process.
Remove the old `nonebot-plugin-taiko-song` installation when applying that
candidate; loading both generations is unsupported and duplicates matchers.
No new `nonebot-plugin-taiko-*` package replaces it.

Current dual-host validation lives in `tests/runtime_ownership/`.
No production cutover is authorized by this document.
