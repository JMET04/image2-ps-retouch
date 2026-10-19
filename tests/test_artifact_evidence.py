from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from artifact_evidence import fingerprint, verify_psd_proof


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.file=Path(self.tmp.name)/'final.psd';self.file.write_bytes(b'original editable data')
        self.proof=dict(evidence_version=2,psd=str(self.file),psd_fingerprint=fingerprint(self.file),
            actual_native_open=True,size=[100,200],bits='BitsPerChannelType.SIXTEEN',
            profile='sRGB IEC61966-2.1',layer_count=2,
            layers=[dict(kind='LayerKind.SMARTOBJECT'),dict(kind='LayerKind.CURVES')])

    def test_valid_proof(self):verify_psd_proof(self.file,self.proof,[100,200])
    def test_modified_file_rejected(self):
        self.file.write_bytes(b'changed file')
        with self.assertRaises(ValueError):verify_psd_proof(self.file,self.proof,[100,200])
    def test_other_path_rejected_even_if_bytes_match(self):
        other=self.file.with_name('other.psd');other.write_bytes(self.file.read_bytes())
        with self.assertRaises(ValueError):verify_psd_proof(other,self.proof,[100,200])
    def test_wrong_canvas_rejected(self):
        with self.assertRaises(ValueError):verify_psd_proof(self.file,self.proof,[200,100])
    def test_legacy_proof_cannot_accept_new_final(self):
        self.proof.pop('evidence_version')
        with self.assertRaises(ValueError):verify_psd_proof(self.file,self.proof,[100,200])
    def test_flattened_report_rejected(self):
        self.proof['layers']=[dict(kind='LayerKind.NORMAL')]
        with self.assertRaises(ValueError):verify_psd_proof(self.file,self.proof,[100,200])

if __name__=='__main__':unittest.main()
