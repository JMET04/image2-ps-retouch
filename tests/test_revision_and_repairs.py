import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from local_lighting import compile_local_light
from repair_patches import compile_patch
from revision_source import validate_revision
from artifact_evidence import fingerprint


class RevisionSafety(unittest.TestCase):
    def test_revision_rejects_changed_base_or_wrong_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);src=p/'original.jpg';src.write_bytes(b'original')
            psd=p/'base.psd';psd.write_bytes(b'editable PSD fixture')
            recipe=p/'recipe.json';recipe.write_text(json.dumps({'source':str(src)}))
            def write(name,obj):
                path=p/name;path.write_text(json.dumps(obj));return str(path)
            evidence=write('execution.json',{'evidence_version':2,'source_sha256':fingerprint(src)['sha256'],
                'original_unchanged':True,'saved_psd':True,'recipe':str(recipe),
                'recipe_fingerprint':fingerprint(recipe),'output_fingerprints':[fingerprint(psd)]})
            proof=write('inspection.json',{'actual_native_open':True,'psd':str(psd),
                'psd_fingerprint':fingerprint(psd),'bits':'BitsPerChannelType.SIXTEEN',
                'profile':'sRGB IEC61966-2.1','size':[4000,3000],'layer_count':2,
                'layers':[{'kind':'LayerKind.SMARTOBJECT'}]})
            spec={'psd':str(psd),'execution':evidence,'inspection':proof}
            self.assertEqual(validate_revision(spec,src)['canvas'],[4000,3000])
            psd.write_bytes(b'altered')
            with self.assertRaises(ValueError):validate_revision(spec,src)
            psd.write_bytes(b'editable PSD fixture');src.write_bytes(b'wrong original')
            with self.assertRaises(ValueError):validate_revision(spec,src)


class RepairSafety(unittest.TestCase):
    def setUp(self):
        def region(x):return {'feather_px':3,'contours':[{'operation':'add',
            'points':[[x,.4],[x+.005,.4],[x+.005,.405],[x,.405]]}]}
        self.compiled={'canvas':[4000,3000],'regions':{'target':region(.4),'donor':region(.45)}}
        self.step={'kind':'clone_patch','name':'small observed dust','target_id':'target',
            'donor_id':'donor','category':'dust','purpose':'small dust; donor same sky tone'}
    def test_feather_support_and_donor_translation(self):
        native,proof=compile_patch(self.step,self.compiled)
        self.assertEqual(native['donor_bounds'],[1789,1189,1831,1226])
        self.assertAlmostEqual(native['target_bounds'][0],1589)
        self.assertEqual(proof['feather_px'],3)
    def test_reject_overlap_large_patch_and_injected_geometry(self):
        bad=copy.deepcopy(self.compiled);bad['regions']['donor']=copy.deepcopy(bad['regions']['target'])
        with self.assertRaises(ValueError):compile_patch(self.step,bad)
        with self.assertRaises(ValueError):compile_patch(dict(self.step,donor_bounds=[0,0,4,4]),self.compiled)
        bad=copy.deepcopy(self.compiled)
        for key in bad['regions']:
            for point in bad['regions'][key]['contours'][0]['points']:point[1]*=10
        with self.assertRaises(ValueError):compile_patch(self.step,bad)


class ExposureResponse(unittest.TestCase):
    def test_lift_rolloff_and_monotonicity(self):
        for action in ['dodge','burn']:
            for stops in [.1,.5,1]:
                c,_=compile_local_light({'kind':'local_light','name':'light','action':action,
                    'response':'exposure','stops':stops,'purpose':'shape visible plane',
                    'region':{'kind':'annotation','id':'plane'}})
                pts=c['channels']['composite'];self.assertEqual(pts[0],[0,0]);self.assertEqual(pts[-1],[255,255])
                self.assertLessEqual(len(pts),14)
                self.assertTrue(all(a[1]<b[1] for a,b in zip(pts,pts[1:])))
                self.assertTrue(all((y>x if action=='dodge' else y<x) for x,y in pts[1:-1]))
        with self.assertRaises(ValueError):compile_local_light({'response':'exposure','stops':2,
            'action':'dodge','purpose':'bad','region':{'kind':'annotation','id':'plane'}})


if __name__=='__main__':unittest.main()
