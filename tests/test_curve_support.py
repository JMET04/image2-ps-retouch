from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from reference_match import fit_channel, curve_coverage


class CurveSupportTests(unittest.TestCase):
    def test_unobserved_shadows_are_protected_without_erasing_midtone_fit(self):
        x=np.linspace(104,120,1000);y=x+25
        legacy=np.array(fit_channel(x,y))
        guarded=np.array(fit_channel(x,y,uncovered_identity_weight=1.0))
        self.assertLess(abs(guarded[2,1]-48),abs(legacy[2,1]-48))
        self.assertLess(abs(np.interp(112,guarded[:,0],guarded[:,1])-137),4)
        self.assertTrue(np.all(np.diff(guarded[:,1])>=0))

    def test_coverage_exposes_narrow_training_range(self):
        report=curve_coverage(np.linspace(104,120,1000))
        self.assertEqual(report['sample_range'],[104.0,120.0])
        self.assertIn(48.0,report['unsupported_knots'])
        self.assertNotIn(112.0,report['unsupported_knots'])

    def test_default_stays_compatible(self):
        x=np.linspace(10,245,1000)
        self.assertEqual(fit_channel(x,x+2),fit_channel(x,x+2,uncovered_identity_weight=0))

    def test_nonfinite_samples_and_negative_weight_rejected(self):
        x=np.linspace(10,240,50)
        with self.assertRaises(ValueError):fit_channel(x,x,uncovered_identity_weight=-1)
        x[5]=np.nan
        with self.assertRaises(ValueError):fit_channel(x,x)


if __name__=='__main__':unittest.main()
