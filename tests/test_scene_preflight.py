import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scene_repairs import compile_scene_patch
from vision_preflight import validate_preflight
from photo_annotations import sha
from photoshop_job import validate


class ScenePatchSafety(unittest.TestCase):
    def setUp(self):
        target = {'feather_px': 0, 'feather_mode': 'per_contour', 'contours': [
            {'operation': 'add', 'feather_px': 20,
             'points': [[0, .1], [.4, .1], [.4, .25], [0, .25]]},
            {'operation': 'subtract', 'feather_px': 3,
             'points': [[0, .2], [.4, .2], [.4, 1], [0, 1]]}]}
        donor = {'feather_px': 20, 'contours': [{
            'operation': 'add', 'points': [[.5, .1], [.9, .1], [.9, .25], [.5, .25]]}]}
        self.compiled = {'canvas': [4000, 3000], 'regions': {'t': target, 'd': donor}}
        self.step = dict(kind='scene_patch', name='Observed window ghost', category='glass_reflection',
                         target_id='t', donor_id='d', purpose='Remove visible double outline',
                         protected_structure='Real snow ridge', donor_review='Clean same-photo sky')

    def test_frame_clipping_translation_and_protection_preserved(self):
        native, proof = compile_scene_patch(self.step, self.compiled)
        self.assertEqual(native['target_bounds'][0], 0)
        self.assertEqual(native['donor_bounds'][0], 2000)
        self.assertEqual([b-a for a,b in zip(native['target_bounds'], native['donor_bounds'])],
                         [2000, 0, 2000, 0])
        self.assertEqual(native['region']['contours'][1]['operation'], 'subtract')
        self.assertIn('pending', proof['acceptance'])

    def test_reject_deformation_subpixel_missing_protection_and_outside_donor(self):
        for change in ('deform', 'subpixel', 'outside', 'broad', 'huge'):
            data = copy.deepcopy(self.compiled)
            if change == 'deform': data['regions']['d']['contours'][0]['points'][1][0] -= .01
            if change == 'subpixel':
                for pt in data['regions']['d']['contours'][0]['points']: pt[0] += .0001
            if change == 'outside':
                for pt in data['regions']['d']['contours'][0]['points']: pt[0] += .11
            if change == 'broad': data['regions']['t']['broad_feather_px'] = 350
            if change == 'huge':
                for key in ('t', 'd'):
                    data['regions'][key]['contours'][0]['points'][2][1] = .8
                    data['regions'][key]['contours'][0]['points'][3][1] = .8
            with self.subTest(change=change), self.assertRaises(ValueError):
                compile_scene_patch(self.step, data)
        for spec in (dict(self.step, protected_structure=''), dict(self.step, rgb_offset=[40,0,0]),
                     dict(self.step, donor_bounds=[0,0,10,10])):
            with self.assertRaises(ValueError): compile_scene_patch(spec, self.compiled)


class DiagnosisBinding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root/'source.jpg'
        self.reference = self.root/'reference.png'
        Image.new('RGB', (100, 80), 'blue').save(self.source)
        Image.new('RGB', (100, 80), 'white').save(self.reference)
        self.path = self.root/'diagnosis.json'
        self.record = dict(schema_version=1, method='chatgpt_vision',
            source=dict(path=str(self.source), sha256=sha(self.source)), subject='Snow ridge',
            visual_hierarchy='Ridge then water', observed_key_light='Existing sunlit slopes',
            diagnosed_at='2026-10-21T14:00:00+08:00',
            views_actually_reviewed=[dict(path=str(self.source), sha256=sha(self.source))],
            defects=[dict(id='ghost', observation='Visible doubled outline', location='Left sky',
                classification='glass_reflection', decision='repair', reason='Clean donor sky',
                reference_instruction='Remove double outline; preserve ridge', acceptance='No seam at 100%')],
            new_reference=dict(path=str(self.reference), sha256=sha(self.reference),
                generated_at='2026-10-21T14:10:00+08:00', visual_comparison='Ghost absent; ridge preserved'))

    def check(self, record=None):
        self.path.write_text(json.dumps(record or self.record), encoding='utf-8')
        return validate_preflight(self.path, self.source, {'path':str(self.reference)})

    def test_reference_observation_and_source_are_all_bound(self):
        self.assertEqual(self.check()['defect_ids'], ['ghost'])
        for section in ('source', 'views_actually_reviewed', 'new_reference'):
            data = copy.deepcopy(self.record)
            obj = data[section][0] if isinstance(data[section], list) else data[section]
            obj['sha256'] = 'wrong'
            with self.subTest(section=section), self.assertRaises(ValueError): self.check(data)

    def test_reject_late_diagnosis_and_vague_decision(self):
        data = copy.deepcopy(self.record); data['diagnosed_at'] = '2026-10-21T14:20:00+08:00'
        with self.assertRaises(ValueError): self.check(data)
        for key in ('decision','acceptance','reference_instruction'):
            data = copy.deepcopy(self.record); data['defects'][0][key] = ''
            with self.subTest(key=key), self.assertRaises(ValueError): self.check(data)

    def test_scene_repair_rejected_after_adjustment_or_without_diagnosis(self):
        base = dict(source=str(self.source), output_base=str(self.root/'out'),
                    selection=dict(original_review='Viewed original'),
                    reference=dict(path=str(self.reference), prompt='Clean sky', comparison='Reviewed'),
                    steps=[dict(kind='curves', name='Light', channels={'composite':[[0,0],[255,255]]}),
                           dict(kind='scene_patch', name='Repair')])
        with self.assertRaisesRegex(ValueError, 'precede'): validate(base)
        base['steps'].reverse()
        with self.assertRaisesRegex(ValueError, 'diagnosis'): validate(base)


if __name__ == '__main__': unittest.main()
