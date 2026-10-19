import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from project_health import inspect


class HealthTests(unittest.TestCase):
    def make_project(self, root, photos, completed=0):
        batch=root/'重修第二版'
        for folder in ('迭代','配方','成片'):(batch/folder).mkdir(parents=True)
        (batch/'批次状态.json').write_text(json.dumps(dict(completed=completed,photos=photos)),encoding='utf-8')
        return batch

    def test_saved_final_is_exposed_without_marking_accepted(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);batch=self.make_project(root,[dict(source='X.jpg',accepted=False)])
            base=batch/'成片/X_redo_v2_r3'
            base.with_suffix('.jpg').write_bytes(b'jpeg')
            base.with_suffix('.psd').write_bytes(b'psd')
            (batch/'成片/X_redo_v2_r3_execution.json').write_text(json.dumps(dict(original_unchanged=True,saved_psd=True)),encoding='utf-8')
            report=inspect(root)
            self.assertEqual(report['completed'],0)
            self.assertEqual(report['pending'][0]['saved_final_candidate']['round'],3)
            self.assertTrue(report['pending'][0]['saved_final_candidate']['files_present'])
            self.assertIn('before any resubmission',report['pending'][0]['next_action'])

    def test_old_unexecuted_recipe_does_not_override_new_saved_round(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);batch=self.make_project(root,[dict(source='X.jpg',accepted=False)])
            (batch/'迭代/X_match_r4_execution.json').write_text(json.dumps(dict(original_unchanged=True)),encoding='utf-8')
            for number in (1,5):
                (batch/f'配方/X_match_r{number}.json').write_text(json.dumps(dict(output_base=str(batch/f'迭代/X_match_r{number}'))),encoding='utf-8')
            row=inspect(root)['pending'][0]
            self.assertEqual(row['latest_saved_round'],4)
            self.assertTrue(row['unexecuted_recipe'].endswith('X_match_r5.json'))

    def test_count_and_missing_deliverables_are_not_hidden(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);self.make_project(root,[dict(source='X.jpg',accepted=True)],completed=0)
            report=inspect(root)
            self.assertFalse(report['count_consistent'])
            self.assertEqual(report['completed'],1)
            self.assertEqual(len(report['missing_accepted_files']),3)


if __name__=='__main__':unittest.main()
