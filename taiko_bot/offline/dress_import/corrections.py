"""Verified broken references in official package 40, applied at import only."""


def correct_catalog(catalog):
    corrections = []
    for entry in catalog['bodyIconList']:
        if entry['id'] != 144:
            continue
        broken = '/dressup/special/head_290_144/body_290_144/cos_290_144/body_290_144.png'
        if entry['url'].endswith(broken):
            entry['url'] = entry['url'].replace(broken, '/dressup/290/body/body_290_144.png')
            corrections.append('body:144 main image: use existing standard body asset instead of 404 reference')
            # This standard spear/armor body incorrectly borrows balloon-head
            # 144 palettes and sword-body 136 skin. Those overlays create loose
            # floating faces; one palette also contains 63 nonexistent URLs.
            # Its standard transparent body asset needs the normal base only.
            entry.pop('special', None)
            corrections.append('body:144 remove unrelated head-144 balloon and body-136 sword overlays')
    catalog['sourceCorrections'] = corrections
    return catalog
