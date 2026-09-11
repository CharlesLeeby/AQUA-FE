#!/usr/bin/env python3
"""Build the offline blind page from frozen sources and reference fields only."""
import base64
import csv
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / 'papers/frontend_searaft_real_correspondence_v1'
FIELDS = 'pair_id query_id sequence source_raw target_raw gap_frames source_x source_y blind_sheet reference_status target_x target_y uncertainty_px annotator_identity annotation_kind human_confirmed notes'.split()
EXTRA = ['annotation_conditions', 'human_confirmed_at']


def read(path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def main():
    manifest = [r for r in read(PAPER / 'pair_query_manifest.csv') if r['cell_status'] == 'SELECTED']
    refs = read(PAPER / 'reference_annotations.csv')
    key = lambda r: (r['pair_id'], r['query_id'])
    indexed = {key(r): r for r in refs}
    assert len(manifest) == len(refs) == len(indexed) == 92
    assert set(indexed) == {key(r) for r in manifest}
    images, items = {}, []
    for row in manifest:
        item = {f: indexed[key(row)][f] for f in FIELDS}
        item.update({f: indexed[key(row)].get(f, '') for f in EXTRA})
        item.update(width=int(row['width']), height=int(row['height']))
        for f in ['source_image', 'target_image']:
            path = Path(row[f])
            image_id = path.name
            raw = path.read_bytes()
            assert raw[:8] == b'\x89PNG\r\n\x1a\n'
            assert struct.unpack('>II', raw[16:24]) == (item['width'], item['height'])
            data = 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')
            if image_id in images:
                assert images[image_id] == data
            else:
                images[image_id] = data
            item[f] = image_id
        items.append(item)
    payload = json.dumps(dict(fields=FIELDS + EXTRA, items=items, images=images), ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    template = (ROOT / 'scripts/templates/searaft_annotate.html').read_text()
    assert template.count('__BLIND_DATA__') == 1
    (PAPER / 'annotate.html').write_text(template.replace('__BLIND_DATA__', payload))
    print('Built annotate.html: {} items, {} embedded original PNGs; no predictions read.'.format(len(items), len(images)))


if __name__ == '__main__':
    main()
