"""Actual private QQ migration code issuance, transfer and receipt replay."""
async def migration_main():
 from taiko_bot.runtime.player.center import bot_qq_migration as migration
 migration.secrets=types.SimpleNamespace(token_hex=lambda n:'c'*32,compare_digest=__import__('hmac').compare_digest)
 observations=[]
 for legacy in [True,False]:
  reset()
  issued=await dispatch(old['qq_migration_code'] if legacy else identity.qq_migration_code,'迁移验证码','onebot',target=False,private=True)
  assert not issued[1] and 'c'*32 in str(issued),issued
  assert db.rows('taiko_qq_migration_codes')[0][1]==hashlib.sha256(('c'*32).encode()).hexdigest()
  command='绑定QQ 67890 '+'c'*32
  migrated=await dispatch(old['bind_qq'] if legacy else identity.bind_qq,command,'qq',target=False,private=True)
  assert not migrated[1] and '历史绑定' in str(migrated),migrated
  rows=db.rows('taiko_qq_migration_codes');assert rows[0][5]==principals[1] and rows[0][6]
  before=effects()
  again=await dispatch(old['bind_qq'] if legacy else identity.bind_qq,command,'qq',target=False,private=True)
  assert effects()==before and not again[1] and '当前绑定' in str(again),again
  observations.append((issued,migrated,again,effects(),rows))
 assert observations[0]==observations[1],observations
 assert not violations,violations
 print(a.host,'private code / migration / replay SQL parity PASS',flush=True)
asyncio.run(migration_main())
