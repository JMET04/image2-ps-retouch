import copy
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from photo_annotations import initialize, compile_annotations, digest


class FeatherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / 'baseline.png'
        Image.new('RGB', (100,100)).save(path)
        self.data = initialize(path, path)
        self.data['regions'] = [dict(id='sky', label='Sky', intent='Protect subject',
            edge_notes='Observed boundary', confidence='high', feather_px=10,
            contours=[dict(kind='polygon',view_id='baseline',operation='add',
                           points=[[0,0],[1,0],[1,1],[0,1]])])]

    def test_legacy_keeps_final_feather(self):
        r = compile_annotations(self.data, False)['regions']['sky']
        self.assertEqual(r['feather_px'], 10)
        self.assertNotIn('feather_px', r['contours'][0])

    def test_independent_feather_survives_compilation(self):
        r = self.data['regions'][0]
        old_digest = digest(self.data)
        r.update(feather_mode='per_contour', feather_px=0)
        r['contours'][0]['feather_px'] = 10
        hole = copy.deepcopy(r['contours'][0]);hole.update(operation='subtract',feather_px=2)
        r['contours'].append(hole)
        result = compile_annotations(self.data, False)['regions']['sky']
        self.assertEqual([c['feather_px'] for c in result['contours']], [10,2])
        self.assertEqual(result['feather_mode'], 'per_contour')
        self.assertNotEqual(old_digest, digest(self.data))

    def test_ambiguous_or_invalid_feather_rejected(self):
        r = self.data['regions'][0]
        r['contours'][0]['feather_px'] = 2
        with self.assertRaises(ValueError):compile_annotations(self.data, False)
        r.update(feather_mode='per_contour')
        with self.assertRaises(ValueError):compile_annotations(self.data, False)
        r['feather_px']=0;r['contours'][0]['feather_px']=-1
        with self.assertRaises(ValueError):compile_annotations(self.data, False)


if __name__ == '__main__':unittest.main()
