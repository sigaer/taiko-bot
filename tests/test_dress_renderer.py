import json

import pytest
from PIL import Image

from taiko_bot.offline.dress_import.__main__ import prepare
from taiko_bot.offline.dress_import.package import DataParser
from taiko_bot.offline.dress_import.corrections import correct_catalog
from taiko_bot.runtime.player.dress_renderer import load_catalog, plan_layers, render_dress


def catalog():
    return {
        'schemaVersion': 1,
        'cosIconList': {0: {'id': 0, 'url': ''}},
        'headIconList': {0: {'id': 0, 'url': ''}},
        'bodyIconList': {0: {'id': 0, 'url': ''}},
        'paintIconList': {0: {'id': 0, 'url': 'paint.png'}},
        'accessoriesIconList': {},
        'bodyColorList': [{'url': 'body.png'}],
        'skinColorList': [{'url': 'skin.png'}],
        'headColorList': [{'url': 'face.png'}],
        'defaultLine': 'line.png', 'specialHeadPaintListMap': {},
    }


def paths(c, **costume):
    return [layer.path for layer in plan_layers(dict(color_face=0, color_body=0, color_limb=0, **costume), c)]


def test_default_order_and_zero_color_ids():
    assert paths(catalog()) == ['body.png', 'skin.png', 'line.png', 'face.png', 'paint.png']


def test_suit_replaces_all_base_palettes_and_preserves_accessory():
    c = catalog()
    c['cosIconList'][52] = {'id': 52, 'url': 'cos.png', 'special': {
        'skinColorList': [{'url': 'custom_skin.png'}],
        'line': 'custom_line.png', 'lineHasFace': True, 'lineZIndex': 4,
    }}
    c['accessoriesIconList'][188] = {'url': 'accessories/accF_290_188.png'}
    assert paths(c, costume_1=52, costume_5=188) == [
        'custom_skin.png', 'cos.png', 'custom_line.png', 'accessories/accF_290_188.png',
    ]


def test_head_face_mask_suppresses_paint_with_ordinary_body():
    c = catalog()
    c['headIconList'][144] = {'id': 144, 'url': 'head.png', 'special': {
        'lineHasFace': True, 'line': 'head_line.png',
        'specialHeadToHeadColorList': [{'url': 'head_face.png'}],
        'specialHeadToHeadColorZIndex': 5,
    }}
    result = paths(c, costume_2=144)
    assert 'paint.png' not in result
    assert 'head_line.png' in result
    assert 'line.png' not in result
    assert result[-1] == 'head_face.png'


def test_body_z_order_and_adapted_paint():
    c = catalog()
    c['bodyIconList'][127] = {'url': 'suit_body.png', 'special': {
        'specialBodyZIndex': 5,
        'specialBodyToSkinColorList': [{'url': 'extra_skin.png'}],
        'specialBodyToBodyColorList': [{'url': 'extra_body.png'}],
        'specialPaintZIndex': 7,
    }}
    c['specialHeadPaintListMap']['0'] = [{'url': 'adapted_paint.png'}]
    result = paths(c, costume_3=127)
    assert result.index('extra_skin.png') < result.index('extra_body.png') < result.index('face.png')
    assert result[-1] == 'adapted_paint.png'


@pytest.mark.parametrize('level,expected', [(0, 'level1.png'), (1, 'level7.png'), (999, 'default.png')])
def test_dan_suit_uses_catalog_level_ids(level, expected):
    c = catalog()
    c['cosIconList'][36] = {'url': 'default.png', 'levelList': [
        {'id': 0, 'url': 'level1.png'}, {'id': 1, 'url': 'level7.png'},
    ]}
    assert expected in paths(c, costume_1=36, got_dan_max=level)


def test_import_uses_game_id_instead_of_url_suffix():
    domain = 'https://taiko-file.gzheyoukeji.com/tk/dev/material/'
    c = {name: [] for name in ('cosIconList', 'headIconList', 'bodyIconList', 'paintIconList')}
    c['accessoriesIconList'] = [
        {'id': 106, 'url': domain + 'dressup/290/acc/accF_290_125.png'},
        {'id': 188, 'url': domain + 'dressup/290/acc/accF_290_005.png'},
    ]
    normalized, files = prepare(c)
    assert normalized['accessoriesIconList'][0]['url'] == 'accessories/accF_290_106.png'
    assert files['accessories/accF_290_188.png'].endswith('accF_290_005.png')


def test_data_parser_rejects_executable_input():
    with pytest.raises(ValueError, match='Unknown data symbol'):
        DataParser('require("fs")', {}, {}).value()
    assert DataParser('{id:0,flag:!0,list:["a",2]}', {}, {}).value() == {
        'id': 0, 'flag': True, 'list': ['a', 2],
    }


def test_body_144_correction_removes_unrelated_balloon_layers():
    c = {'bodyIconList': [{'id': 144, 'url': 'https://taiko-file.gzheyoukeji.com/tk/dev/material/dressup/special/head_290_144/body_290_144/cos_290_144/body_290_144.png',
                          'special': {'specialBodyToBodyColorList': [{'url': 'balloon.png'}]}}]}
    result = correct_catalog(c)
    assert result['bodyIconList'][0]['url'].endswith('/dressup/290/body/body_290_144.png')
    assert 'special' not in result['bodyIconList'][0]
    assert len(result['sourceCorrections']) == 2


def test_pixel_composition_and_catalog_revision(tmp_path):
    c = catalog()
    for name in ('cosIconList', 'headIconList', 'bodyIconList', 'paintIconList', 'accessoriesIconList'):
        c[name] = list(c[name].values())
    (tmp_path / 'catalog.json').write_text(json.dumps(c))
    colors = {'body.png': (255, 0, 0, 255), 'skin.png': (0, 0, 0, 0),
              'line.png': (0, 0, 0, 0), 'face.png': (0, 0, 0, 0), 'paint.png': (0, 0, 255, 128)}
    for name, color in colors.items():
        Image.new('RGBA', (2, 2), color).save(tmp_path / name)
    image = render_dress({'profile': {'gameCostume': {'color_body': 0, 'color_limb': 0}}}, tmp_path)
    assert image.getpixel((0, 0)) == (127, 0, 128, 255)
    before = load_catalog(tmp_path)
    c['defaultLine'] = 'other.png'
    (tmp_path / 'catalog.json').write_text(json.dumps(c))
    assert load_catalog(tmp_path) is not before


def test_asset_path_cannot_escape_root(tmp_path):
    c = catalog()
    c['defaultLine'] = '../private.png'
    for name in ('cosIconList', 'headIconList', 'bodyIconList', 'paintIconList', 'accessoriesIconList'):
        c[name] = list(c[name].values())
    (tmp_path / 'catalog.json').write_text(json.dumps(c))
    with pytest.raises(ValueError, match='escapes'):
        render_dress({'profile': {'gameCostume': {}}}, tmp_path)
