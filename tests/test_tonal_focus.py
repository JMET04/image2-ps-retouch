"""Tonal targeting must protect the opposite range and keep valid curves."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from local_lighting import light_curve, compile_local_light


class TonalFocusTests(unittest.TestCase):
    def test_every_focus_preserves_order_direction_and_endpoints(self):
        for action in ('dodge', 'burn'):
            for focus in ('all', 'shadows', 'midtones', 'highlights'):
                for strength in range(101):
                    curve = light_curve(action, strength, focus)
                    self.assertEqual(curve[0], [0, 0])
                    self.assertEqual(curve[-1], [255, 255])
                    self.assertTrue(all(0 <= y <= 255 for _, y in curve))
                    self.assertTrue(all(a[1] < b[1] for a, b in zip(curve, curve[1:])))
                    self.assertTrue(all(y >= x if action == 'dodge' else y <= x for x, y in curve))

    def test_highlight_burn_keeps_shadow_reflection_readable(self):
        curve = dict(light_curve('burn', 80, 'highlights'))
        self.assertLess(64 - curve[64], 9)
        self.assertGreater(192 - curve[192], 50)

    def test_shadow_fill_does_not_wash_out_lit_snow(self):
        curve = dict(light_curve('dodge', 80, 'shadows'))
        self.assertGreater(curve[64] - 64, 50)
        self.assertLess(curve[192] - 192, 9)

    def test_existing_default_and_neutral_results_stay_compatible(self):
        for action in ('dodge', 'burn'):
            self.assertEqual(light_curve(action, 42), light_curve(action, 42, 'all'))
            for focus in ('all', 'shadows', 'midtones', 'highlights'):
                self.assertTrue(all(x == y for x, y in light_curve(action, 0, focus)))
        self.assertEqual(dict(light_curve('burn', 32))[128], 93.0638)

    def test_provenance_and_invalid_target(self):
        step = dict(kind='local_light', name='Snow mass', action='burn', strength=65,
                    tonal_focus='highlights', purpose='Lower competing lit snow while preserving reflected light in the trees',
                    region=dict(kind='annotation', id='right_snow'))
        compiled, proof = compile_local_light(step)
        self.assertEqual(proof['tonal_focus'], 'highlights')
        self.assertEqual(compiled['channels']['composite'], proof['native_curve_points'])
        for bad in ('automatic', '', None, 3, [], {}):
            with self.assertRaises(ValueError):
                light_curve('burn', 50, bad)


    def test_explicit_snow_ceiling_preserves_order_and_shadow_fill(self):
        for focus in ('all', 'shadows', 'midtones', 'highlights'):
            for strength in range(101):
                for ceiling in (200, 225, 250, 255):
                    curve = light_curve('burn', strength, focus, ceiling)
                    self.assertEqual(curve[-1], [255, ceiling])
                    self.assertEqual(curve[0], [0, 0])
                    self.assertTrue(all(a[1] < b[1] for a, b in zip(curve, curve[1:])))
                    self.assertTrue(all(0 <= y <= x for x, y in curve))
        default = dict(light_curve('burn', 78, 'highlights'))
        lowered = dict(light_curve('burn', 78, 'highlights', 225))
        self.assertLess(default[64] - lowered[64], 0.5)
        self.assertGreater(default[224] - lowered[224], 20)

    def test_ceiling_validation_and_provenance(self):
        for bad in (True, None, '225', 199, 256, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                light_curve('burn', 50, 'highlights', bad)
        with self.assertRaises(ValueError):
            light_curve('dodge', 50, 'all', 225)
        step = dict(name='Snow shelf', action='burn', strength=60, white_ceiling=225,
                    purpose='Quiet the nearest snow without blackening grass',
                    region=dict(kind='annotation', id='near_snow'))
        compiled, proof = compile_local_light(step)
        self.assertEqual(proof['white_ceiling'], 225)
        self.assertEqual(compiled['channels']['composite'][-1], [255, 225])


if __name__ == '__main__':
    unittest.main()
