import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from codec_v8 import container_from_file,unpack_container,self_test,SHARD_BYTES
from assemble_smw_v8 import load
from read_smw_v8 import Paper


class PaperArchiveTests(unittest.TestCase):
    def test_error_correction_and_whole_row_column_losses(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            source=Path(directory)/'example.bin'
            original=np.random.default_rng(648100).integers(0,256,16384,dtype='uint8').tobytes()
            source.write_bytes(original)
            container,metadata,_=container_from_file(source)
            shards=self_test(container,metadata)
            raw,recovered_metadata=unpack_container(container)
            self.assertEqual(raw,original)
            self.assertEqual(recovered_metadata,metadata)
            self.assertEqual(len(shards),342)

    def test_hash_rejects_corrupted_compressed_data(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            source=Path(directory)/'example.bin';source.write_bytes(b'paper archive test'*500)
            container,_,_=container_from_file(source)
            damaged=bytearray(container);damaged[-1]^=1
            with self.assertRaisesRegex(ValueError,'SHA256 mismatch'):
                unpack_container(bytes(damaged))

    def test_cache_is_next_to_scan_not_source_code(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            scan=Path(directory)/'independent.bmp'
            cache=scan.parent/(scan.stem+'-enhanced-v8');cache.mkdir()
            value=bytes((i%251 for i in range(SHARD_BYTES)))
            (cache/'tile-042.bin').write_bytes(value)
            parts,blocks=load(scan)
            self.assertEqual(bytes(parts[42][0]),value)
            self.assertTrue(parts[42][1].all())
            self.assertFalse(parts[41][1].any())

    def test_registration_ignores_long_scanner_edge(self):
        mask=np.zeros((100,100),dtype=bool);mask[:,1]=True
        mask[30:50,40:60]=True;mask[35:45,45:55]=False
        self.assertEqual(Paper.component_center(mask,0,0),[49.5,39.5])


if __name__=='__main__':unittest.main()
