"""Validate all costume rules against staged assets using synthetic profiles."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw

from taiko_bot.runtime.player.dress_renderer import load_catalog, plan_layers, render_dress


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    raw = json.loads((args.root / 'catalog.json').read_text())

    def references(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from references(item)
        elif isinstance(value, list):
            for item in value:
                yield from references(item)
        elif isinstance(value, str) and value.endswith('.png'):
            yield value

    dimensions = Counter()
    for relative in sorted(set(references(raw))):
        with Image.open(args.root / relative) as image:
            dimensions[image.size] += 1
            image.verify()
    catalog = load_catalog(args.root)
    rendered = 0
    samples = []
    base = {'color_face': 0, 'color_body': 1, 'color_limb': 8}
    for group, field in [('cosIconList', 'costume_1'), ('headIconList', 'costume_2'),
                         ('bodyIconList', 'costume_3'), ('paintIconList', 'costume_4'),
                         ('accessoriesIconList', 'costume_5')]:
        for identifier, entry in catalog[group].items():
            for color in (0, 31, 62):
                costume = dict(base, **{field: identifier, 'color_face': color, 'color_body': color, 'color_limb': color})
                for layer in plan_layers(costume, catalog):
                    assert (args.root / layer.path).is_file(), layer.path
                image = render_dress({'profile': {'gameCostume': costume}}, args.root)
                assert image.getbbox() is not None, (group, identifier)
                rendered += 1
                if color == 0 and (entry.get('special') or identifier in (36, 106, 144, 188, 226)):
                    image.thumbnail((200, 170))
                    samples.append((f'{group.removesuffix("IconList")} {identifier}', image.copy()))
    # Exhaust every supported palette and head-adapted paint, not just defaults.
    special_cases = []
    for group, field in [('cosIconList', 'costume_1'), ('headIconList', 'costume_2'), ('bodyIconList', 'costume_3')]:
        for identifier, entry in catalog[group].items():
            if entry.get('special'):
                special_cases.extend(dict(base, **{field: identifier, 'color_face': i, 'color_body': i, 'color_limb': i}) for i in range(63))
    for head, paints in catalog['specialHeadPaintListMap'].items():
        special_cases.extend(dict(base, costume_2=int(head), costume_4=i) for i in range(len(paints)))
    suit = catalog['cosIconList'][36]
    special_cases.extend(dict(base, costume_1=36, got_dan_max=row['id']) for row in suit['levelList'])
    for costume in special_cases:
        for layer in plan_layers(costume, catalog):
            assert (args.root / layer.path).is_file(), layer.path
        assert render_dress({'profile': {'gameCostume': costume}}, args.root).getbbox()
        rendered += 1
    sheet = Image.new('RGB', (1000, ((len(samples) + 4) // 5) * 200), '#eeeeee')
    draw = ImageDraw.Draw(sheet)
    for i, (label, image) in enumerate(samples):
        x, y = (i % 5) * 200, (i // 5) * 200
        sheet.paste(image, (x + (200 - image.width) // 2, y + 25), image)
        draw.text((x + 6, y + 5), label, fill='black')
    sheet.save(args.output / 'special-costumes.jpg')
    evidence = {'status': 'PASS', 'renderedProfiles': rendered,
                'referencedImages': sum(dimensions.values()),
                'dimensions': {str(key): value for key, value in dimensions.items()},
                'groups': {name: len(catalog[name]) for name in ('cosIconList', 'headIconList', 'bodyIconList', 'paintIconList', 'accessoriesIconList')}}
    (args.output / 'validation.json').write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence))


if __name__ == '__main__':
    main()
