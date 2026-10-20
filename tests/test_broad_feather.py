import copy
import math
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from photo_annotations import initialize, compile_annotations, digest


class BroadFeatherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = Path(self.tmp.name) / 'baseline.png'
        Image.new('RGB', (1800, 1200)).save(p)
        self.data = initialize(p, p)
        self.data['regions'] = [dict(id='water', label='Observed water', intent='Broad light field',
            edge_notes='Independent shore protection', confidence='medium', feather_px=0,
            feather_mode='per_contour', broad_feather_px=350, contours=[
                dict(kind='ellipse', view_id='baseline', operation='add', feather_px=0, bounds=[.1,.2,.7,.8]),
                dict(kind='polygon', view_id='baseline', operation='subtract', feather_px=8,
                     points=[[0,0],[1,0],[1,.15],[0,.15]])])]

    def test_broad_field_and_narrow_protection_are_distinct(self):
        r = compile_annotations(self.data, False)['regions']['water']
        self.assertEqual(r['broad_feather_px'], 350)
        self.assertEqual([c['feather_px'] for c in r['contours']], [0,8])
        old = digest(self.data)
        self.data['regions'][0]['broad_feather_px'] = 349
        self.assertNotEqual(old, digest(self.data))

    def test_invalid_or_ambiguous_fields_rejected(self):
        for value in (0, -1, 401, True, math.nan, math.inf, '350'):
            d = copy.deepcopy(self.data); d['regions'][0]['broad_feather_px'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):compile_annotations(d, False)
        for change in ('extra_add','positive_feather','combined'):
            d = copy.deepcopy(self.data); r = d['regions'][0]
            if change == 'extra_add':r['contours'].append(copy.deepcopy(r['contours'][0]))
            elif change == 'positive_feather':r['contours'][0]['feather_px'] = 10
            else:r['feather_mode'] = 'combined'
            with self.subTest(change=change), self.assertRaises(ValueError):compile_annotations(d, False)

    def test_legacy_has_no_new_field(self):
        del self.data['regions'][0]['broad_feather_px']
        self.assertNotIn('broad_feather_px', compile_annotations(self.data,False)['regions']['water'])


if __name__ == '__main__':unittest.main()
