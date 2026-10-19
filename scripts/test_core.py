"""Small regression checks for binary boundaries and read-only extraction invariants."""
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from endfield_audio import AudioVFS, chacha, parse_blc, prepare_output, safe_stem, wwise_hash, xor_audio
from audio_match import waveform_score
import numpy as np


def synthetic_blc(code_version, resource_version=123456, empty=False):
    group=b"Audio"
    chunk=bytes.fromhex("0123456789ABCDEF0123456789ABCDEF")
    name=b"Data/Audio/PCK/Windows/Main/sample.pck"
    tag=bytes({3:0,4:4,5:8}.get(code_version,8))
    raw=struct.pack("<iiH",code_version,resource_version,len(group))+group
    raw+=struct.pack("<qiqBi",0,0 if empty else 1,0 if empty else 100,12,0 if empty else 1)
    if not empty:
        raw+=chunk+bytes(16)+struct.pack("<qB",100,12)+tag+struct.pack("<iH",1,len(name))+name
        raw+=bytes(40)+struct.pack("<qqBB",0,100,12,0)+tag
    raw+=bytes(10)
    raw+=struct.pack("<I",zlib.crc32(raw))
    nonce=struct.pack("<iq",3,99)
    return nonce+chacha(raw,nonce)


class RegressionTests(unittest.TestCase):
    def test_index_versions_and_chunk_byte_order(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"index.blc"
            for version in (3,4,5):
                path.write_bytes(synthetic_blc(version))
                summary,entries=parse_blc(path)
                self.assertEqual(summary["code_version"],version)
                self.assertEqual(summary["trailing_bytes"],10)
                self.assertEqual(entries[0]["chunk_id"],"0123456789ABCDEF0123456789ABCDEF")
                self.assertEqual(entries[0]["length"],100)

    def test_corrupted_and_future_indexes_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"index.blc"
            damaged=bytearray(synthetic_blc(5));damaged[-6]^=0x20;path.write_bytes(damaged)
            with self.assertRaisesRegex(ValueError,"CRC"):
                parse_blc(path)
            path.write_bytes(synthetic_blc(6))
            with self.assertRaisesRegex(ValueError,"Unsupported"):
                parse_blc(path)

    def test_random_access_cipher_alignment(self):
        original=bytes(range(256))*7;nonce=struct.pack("<iq",3,123)
        encrypted=chacha(original,nonce)
        for start in (0,1,63,64,65,511):
            self.assertEqual(chacha(encrypted[start:start+137],nonce,start),original[start:start+137])

    def test_xor_stream_against_scalar_reference(self):
        source=bytes(range(71));seed=0xFFFFFFFD
        def key(index):
            value=0x9C5A0B29
            for shift in (0,8,16,24):
                value=((value^((index>>shift)&255))*81861667)&0xFFFFFFFF
            return value
        for offset in (0,1,2,3,7):
            expected=bytes(b^((key((seed+(offset+i)//4)&0xFFFFFFFF)>>(((offset+i)%4)*8))&255)
                           for i,b in enumerate(source))
            self.assertEqual(xor_audio(source,seed,offset),expected)

    def test_output_cannot_enter_game(self):
        with tempfile.TemporaryDirectory() as folder:
            game=Path(folder)/"game";(game/"Endfield_Data/StreamingAssets/VFS").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError,"outside"):
                prepare_output(game/"exports",game)
            self.assertFalse((game/"exports").exists())

    def test_persistent_snapshot_does_not_resurrect_base_files(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)/"Endfield_Data"
            for layer,empty in [("StreamingAssets",False),("Persistent",True)]:
                path=data/layer/"VFS/24ED34CF/24ED34CF.blc"
                path.parent.mkdir(parents=True);path.write_bytes(synthetic_blc(5,empty=empty))
            self.assertEqual(AudioVFS(data).entries,[])

    def test_newer_cross_block_path_replaces_obsolete_optional_index(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)/"Endfield_Data";(data/"StreamingAssets/VFS").mkdir(parents=True)
            for block,version in [("1EBAF5C6",100),("24ED34CF",200)]:
                path=data/"Persistent/VFS"/block/(block+".blc")
                path.parent.mkdir(parents=True);path.write_bytes(synthetic_blc(5,version))
            entries=AudioVFS(data).entries
            self.assertEqual(len(entries),1)
            self.assertEqual(entries[0]["block"],"24ED34CF")

    def test_output_labels_and_known_event_hash(self):
        self.assertEqual(wwise_hash("au_music_map02_lv010_exploring_scroll_p2"),1739497170)
        for name in ("../escape",r"a\b","CON","bad:","trailing."):
            with self.assertRaises(ValueError):safe_stem(name)

    def test_waveform_match_handles_gain_and_delay(self):
        rng=np.random.default_rng(2026);rate=100
        music=rng.normal(size=1800)
        reference=music[300:1500]*0.4+0.2
        correct=waveform_score(music,reference,rate,0,8)
        wrong=waveform_score(rng.normal(size=1800),reference,rate,0,8)
        self.assertGreater(correct["normalized_waveform_correlation"],0.999)
        self.assertAlmostEqual(correct["alignment_seconds"],3)
        self.assertLess(wrong["normalized_waveform_correlation"],0.3)


if __name__=="__main__":
    unittest.main()
