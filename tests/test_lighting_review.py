"""Validate toggle provenance and collision safety on synthetic test fixtures."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from photo_annotations import initialize,overlay,accept
from photoshop_job import validate

class LightingReviewTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        src=self.root/'source.png';ref=self.root/'reference.png'
        Image.new('RGB',(100,100),(90,120,160)).save(src)
        Image.new('RGB',(100,100),(110,125,160)).save(ref)
        ann=initialize(src,src)
        ann['regions']=[dict(id='plane',label='synthetic plane',intent='fixture only',edge_notes='fixture',confidence='high',feather_px=4,
            contours=[dict(kind='ellipse',view_id='baseline',operation='add',bounds=[.2,.2,.8,.8])])]
        report=overlay(ann,self.root/'overlay.png')
        ann=accept(ann,report,'Synthetic fixture only; not a real photograph acceptance')
        ap=self.root/'ann.json';ap.write_text(json.dumps(ann),encoding='utf-8')
        self.job=dict(stage='retouch',source=str(src),output_base=str(self.root/'output'),annotations=str(ap),
            selection={'original_review':'synthetic fixture'},reference=dict(path=str(ref),prompt='fixture',comparison='fixture'),
            lighting_plan=dict(observed_key_light='fixture',subject_priority='fixture',shape_intent='fixture'),
            lighting_review=True,steps=[dict(kind='curves',name='grade',channels={'composite':[[0,0],[255,255]]}),
                dict(kind='local_light',name='light',action='dodge',strength=12,purpose='fixture',region={'kind':'annotation','id':'plane'})])

    def test_only_light_layers_toggle_and_forged_indices_are_ignored(self):
        self.job['lighting_review_indices']=[0]
        result=validate(self.job)
        self.assertEqual(result['lighting_review_indices'],[1])
        self.assertEqual(result['steps'][1]['kind'],'curves')
        self.assertEqual(result['local_lighting_provenance']['steps'][0]['annotation_id'],'plane')

    def test_existing_off_export_prevents_overwrite(self):
        (self.root/'output_lighting_off.jpg').write_bytes(b'preserved')
        with self.assertRaises(FileExistsError):validate(self.job)
        self.assertEqual((self.root/'output_lighting_off.jpg').read_bytes(),b'preserved')

    def test_missing_light_and_duplicate_names_cannot_claim_comparison(self):
        job=copy.deepcopy(self.job);job['steps']=job['steps'][:1]
        with self.assertRaises(ValueError):validate(job)
        job=copy.deepcopy(self.job);job['steps'][0]['name']='light'
        with self.assertRaises(ValueError):validate(job)

    def test_disabled_comparison_clears_untrusted_indices(self):
        self.job.update(lighting_review=False,lighting_review_indices=[0])
        self.assertNotIn('lighting_review_indices',validate(self.job))

if __name__=='__main__':unittest.main()
