"""Exercise installed center/client personal cards with public assets and fake users."""
import argparse
import hashlib
from importlib import import_module, metadata
from io import BytesIO
import json
import os
from pathlib import Path
import sys

from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dress', type=Path)
    parser.add_argument('public_assets', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--role', choices=('center', 'client'), required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = args.output / 'synthetic-runtime'
    (root / 'assets').mkdir(parents=True, exist_ok=True)
    (root / 'songs').mkdir(exist_ok=True)
    (root / 'songs/song_data.json').write_text('[]')
    for name in ('fonts', 'templates', 'icons', 'name_plate', 'name_plate_dani'):
        link = root / 'assets' / name
        if not link.exists():
            link.symlink_to(args.public_assets / name)
    if not (root / 'assets/dress').exists():
        (root / 'assets/dress').symlink_to(args.dress)
    for name in ('TAIKO_RUNTIME_ROOT', 'TAIKO_CENTER_ROOT', 'TAIKO_OFFLINE_ROOT', 'TAIKO_BOT_ROOT'):
        os.environ[name] = str(root)
    os.environ['TAIKO_USERDATA_DIR'] = str(root / 'userdata')
    os.environ['TAIKO_RUNTIME_ENV_FILE'] = str(root / 'absent.env')
    os.chdir(root)

    def guard(event, values):
        if event in ('socket.connect', 'socket.getaddrinfo', 'sqlite3.connect'):
            raise AssertionError(f'External IO forbidden: {event}')
        if event == 'open' and isinstance(values[0], (str, bytes)):
            path = Path(os.fsdecode(values[0])).resolve()
            if path.is_relative_to('/home/sigaer/taiko') and not path.is_relative_to(args.public_assets.resolve()):
                raise AssertionError('Private production data forbidden')
    sys.addaudithook(guard)
    import nonebot
    nonebot.init(driver='~fastapi+~httpx', log_level='CRITICAL', taiko_song_profile=args.role, taiko_song_public_root=str(root))
    from taiko_bot.runtime.player.dress_renderer import render_dress
    cases = {
        'ordinary': {'costume_2': 1, 'costume_3': 1, 'costume_4': 59, 'costume_5': 106},
        'balloons': {'costume_2': 144, 'costume_3': 144},
        'special-paint': {'costume_2': 154, 'costume_3': 162, 'costume_4': 35},
        'diving-suit': {'costume_1': 52, 'costume_5': 188},
        'dan-zero': {'costume_1': 36, 'got_dan_max': 0},
    }
    evidence = []
    for role in (args.role,):
        module = import_module(f'taiko_bot.runtime.player.{role}.display_support.draw_dress')
        assert Path(module.__file__).is_relative_to(sys.prefix)
        for label, equipped in cases.items():
            costume = dict(color_face=0, color_body=1, color_limb=8, mydon_name='装扮验证', **equipped)
            userdata = {'profile': {'gameCostume': costume, 'mydon_name': '装扮验证'}, 'songs': []}
            shared = render_dress(userdata, args.dress)
            actual = module.build_dress_image(userdata)
            assert actual.size == shared.size and actual.tobytes() == shared.tobytes()
            image = module.render_my_don_image(12345678, userdata=userdata)
            with Image.open(BytesIO(image)) as decoded:
                assert decoded.width > 300 and decoded.height > 300
                size = decoded.size
            (args.output / f'{role}-{label}.png').write_bytes(image)
            evidence.append({'role': role, 'case': label, 'size': size, 'sha256': hashlib.sha256(image).hexdigest()})
    result = {'status': 'PASS', 'version': metadata.version('taiko-bot'), 'cards': evidence}
    (args.output / 'my-don-validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({'status': 'PASS', 'version': result['version'], 'cards': len(evidence)}))


if __name__ == '__main__':
    main()
