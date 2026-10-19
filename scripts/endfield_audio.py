#!/usr/bin/env python3
"""Read-only Endfield audio extraction. See references/format-notes.md for sources."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import wave
import zlib
from pathlib import Path

import numpy as np
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

VFS_KEY = base64.b64decode("6VsxesT4KFadI6hr8nHctT6Eb6dckk1nHbqOOPTKUuE=")
AUDIO_BLOCKS = ("07A1BB91", "1EBAF5C6", "24ED34CF", "F151B649")


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def chacha(data, nonce, byte_offset=0):
    counter, skip = 1 + byte_offset // 64, byte_offset % 64
    if counter > 0xFFFFFFFF:
        raise ValueError("ChaCha20 counter exceeds the supported file range")
    cipher = Cipher(algorithms.ChaCha20(VFS_KEY, struct.pack("<I", counter) + nonce), None).decryptor()
    return (cipher.update(bytes(skip) + data) + cipher.finalize())[skip:]


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, length):
        if length < 0 or self.pos + length > len(self.data):
            raise ValueError(f"Truncated index at byte {self.pos}, requested {length}")
        value = self.data[self.pos:self.pos + length]
        self.pos += length
        return value

    def number(self, fmt):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def text(self):
        return self.take(self.number("<H")).decode("utf-8")


def parse_blc(path):
    path = Path(path)
    raw = path.read_bytes()
    if len(raw) < 20:
        raise ValueError(f"Index too short: {path}")
    data = chacha(raw[12:], raw[:12])
    if zlib.crc32(data[:-4]) != struct.unpack_from("<I", data, len(data) - 4)[0]:
        raise ValueError(f"Index CRC mismatch; changed key, damaged or partially updated file: {path}")
    r = Reader(data[:-4])
    first = r.number("<i")
    code_version, resource_version = (first, r.number("<i")) if first < 11 else (3, first)
    if code_version not in (3, 4, 5):
        raise ValueError(f"Unsupported BLC code version {code_version}; do not guess its layout")
    group = r.text()
    r.take(8)  # group hash
    file_count, total_bytes = r.number("<i"), r.number("<q")
    r.take(1)  # block type
    chunk_count = r.number("<i")
    if not 0 <= chunk_count <= len(data) // 45 or file_count < 0:
        raise ValueError("Invalid index counts")
    entries = []
    tag_size = {3: 0, 4: 4, 5: 8}[code_version]
    for _ in range(chunk_count):
        chunk_id = r.take(16).hex().upper()
        r.take(16)  # chunk content MD5
        chunk_size = r.number("<q")
        r.take(1 + tag_size)
        count = r.number("<i")
        if not 0 <= count <= len(data) // 60:
            raise ValueError("Invalid file count within a chunk")
        for _ in range(count):
            name = r.text()
            r.take(8 + 16 + 16)  # path hash, chunk MD5, file-data MD5
            offset, length = r.number("<q"), r.number("<q")
            r.take(1)
            encrypted = bool(r.number("<B"))
            seed = r.number("<q") if encrypted else 0
            r.take(tag_size)
            if min(offset, length) < 0 or offset + length > chunk_size:
                raise ValueError(f"Invalid resource range: {name}")
            entries.append(dict(name=name, chunk_id=chunk_id, block=path.parent.name,
                                offset=offset, length=length, encrypted=encrypted,
                                seed=seed, group=group, index=str(path)))
    if len(entries) != file_count:
        raise ValueError("Manifest file count does not match its contents")
    # Known indexes have a 10-byte extension after the chunk list.
    return dict(code_version=code_version, resource_version=resource_version,
                group=group, files=file_count, chunks=chunk_count,
                bytes=total_bytes, trailing_bytes=len(r.data)-r.pos), entries


def game_data_path(game):
    path = Path(game).expanduser().resolve()
    if (path / "Endfield_Data").is_dir():
        return path / "Endfield_Data"
    if (path / "StreamingAssets" / "VFS").is_dir():
        return path
    raise ValueError("--game must name the game installation folder or its Endfield_Data folder")


def prepare_output(out, game=None):
    out = Path(out).expanduser().resolve()
    if game is not None:
        data = game_data_path(game)
        protected = data.parent if data.name.lower() == "endfield_data" else data
        if out.is_relative_to(protected):
            raise ValueError("Choose an output directory outside the game installation")
    out.mkdir(parents=True, exist_ok=True)
    return out


class AudioVFS:
    def __init__(self, game):
        self.data = game_data_path(game)
        self.layers = [self.data / "Persistent" / "VFS", self.data / "StreamingAssets" / "VFS"]
        self.summaries, self.entries = [], []
        self._chunks = {}
        for block in AUDIO_BLOCKS:
            # A Persistent block manifest is a complete current snapshot. Do not
            # resurrect deleted base files by merging it with an older manifest.
            indexes = [p / block / (block + ".blc") for p in self.layers]
            index = next((p for p in indexes if p.is_file()), None)
            if index is None:
                continue
            summary, entries = parse_blc(index)
            summary["index"] = str(index)
            self.summaries.append(summary)
            for entry in entries:
                if entry["name"].lower().endswith(".pck"):
                    entry["resource_version"] = summary["resource_version"]
                    self.entries.append(entry)
        if not self.summaries:
            raise FileNotFoundError("No supported audio BLC indexes found")
        # Resources can migrate from an obsolete optional block into Audio.
        # Deduplicate the virtual path using the newer resource snapshot first.
        merged = {}
        for entry in sorted(self.entries, key=lambda e: e["resource_version"]):
            merged[entry["name"]] = entry
        self.entries = list(merged.values())

    def chunk_path(self, entry):
        block = entry["block"]
        if block not in self._chunks:
            lookup = {}
            for layer in reversed(self.layers):
                for p in (layer / block).glob("*.chk"):
                    lookup[p.stem.upper().zfill(32)] = p
            self._chunks[block] = lookup
        path = self._chunks[block].get(entry["chunk_id"])
        if path is None:
            raise FileNotFoundError(f"Missing chunk {entry['chunk_id']} for {entry['name']}; finish the game update")
        return path

    def read(self, entry, offset=0, length=None):
        length = entry["length"] - offset if length is None else length
        if min(offset, length) < 0 or offset + length > entry["length"]:
            raise ValueError("Requested data is outside its indexed resource")
        with self.chunk_path(entry).open("rb") as stream:
            stream.seek(entry["offset"] + offset)
            data = stream.read(length)
        if len(data) != length:
            raise ValueError("Resource is truncated; game update may still be in progress")
        if entry["encrypted"]:
            data = chacha(data, struct.pack("<iq", 3, entry["seed"]), offset)
        return data

    def packages(self):
        return [Package(self, entry) for entry in self.entries]


def xor_audio(data, seed, byte_offset=0):
    padding = byte_offset & 3
    buffer = bytearray(padding) + bytearray(data)
    actual = len(buffer)
    buffer.extend(bytes((-actual) % 4))
    words = np.frombuffer(buffer, dtype="<u4")
    indices = (np.arange(len(words), dtype=np.uint64) + (seed & 0xFFFFFFFF) +
               (byte_offset >> 2)).astype(np.uint32)
    keys = ((indices & np.uint32(255)) ^ np.uint32(0x9C5A0B29)) * np.uint32(81861667)
    for shift in (8, 16, 24):
        keys = (keys ^ ((indices >> np.uint32(shift)) & np.uint32(255))) * np.uint32(81861667)
    words ^= keys
    return bytes(buffer[padding:actual])


def wwise_hash(name):
    """Wwise event names use lowercase FNV-1, not FNV-1a."""
    value = 0x811C9DC5
    for byte in name.lower().encode("utf-8"):
        value = ((value * 0x01000193) & 0xFFFFFFFF) ^ byte
    return value


class Package:
    def __init__(self, vfs, entry):
        self.vfs, self.entry = vfs, entry
        first = self.read(0, 12)
        if first[:4] not in (b":)xD", b"AKPK"):
            raise ValueError(f"Unsupported PCK header: {entry['name']}")
        size = struct.unpack_from("<I", first, 4)[0]
        if not 16 <= size <= min(entry["length"]-8, 64*1024*1024):
            raise ValueError("Invalid or unsupported PCK header length")
        header = self.read(0, size+8)
        if first[:4] == b":)xD":
            header = b"AKPK" + header[4:8] + struct.pack("<I", 1) + xor_audio(header[12:], size)
        if struct.unpack_from("<I", header, 8)[0] != 1:
            raise ValueError("Only little-endian PCK is supported by this helper")
        self.header = header
        lang, banks, sounds = struct.unpack_from("<III", header, 12)
        external, pos = 0, 24
        if lang+banks+sounds+16 < size:
            external, pos = struct.unpack_from("<I", header, pos)[0], pos+4
        pos += lang
        self.banks = self.sector(pos, banks, False)
        pos += banks
        self.sounds = self.sector(pos, sounds, False)
        pos += sounds
        self.externals = self.sector(pos, external, True)

    def read(self, offset, length):
        return self.vfs.read(self.entry, offset, length)

    def sector(self, pos, size, external):
        if not size:
            return []
        if pos+size > len(self.header) or size < 4:
            raise ValueError("Invalid PCK index sector")
        count = struct.unpack_from("<I", self.header, pos)[0]
        if count == 0:
            return []
        width, remainder = divmod(size-4, count)
        if remainder or width not in (20, 24):
            raise ValueError(f"Unsupported PCK entry size {width}")
        result = []
        for i in range(count):
            fmt = "<QIIII" if external and width == 24 else "<IIQII" if width == 24 else "<IIIII"
            id, block, length, offset, language = struct.unpack_from(fmt, self.header, pos+4+i*width)
            offset *= block or 1
            if offset+length > self.entry["length"]:
                raise ValueError("PCK media range exceeds its package")
            result.append(dict(id=id, offset=offset, length=length, language_id=language))
        return result

    def media(self, item):
        data = self.read(item["offset"], item["length"])
        if data[:4] not in (b"RIFF", b"RIFX"):
            data = xor_audio(data, item["id"])
        if data[:4] not in (b"RIFF", b"RIFX") or len(data) < 12 or data[8:12] != b"WAVE":
            raise ValueError(f"Media {item['id']} is not a decoded Wwise RIFF; refusing to label it as audio")
        return data


def bank_nodes(data):
    if data[:4] != b"BKHD":
        raise ValueError("Invalid decoded BNK")
    nodes, pos, bkhd = [], 0, None
    while pos+8 <= len(data):
        name, length = data[pos:pos+4], struct.unpack_from("<I", data, pos+4)[0]
        end = pos+8+length
        if end > len(data):
            raise ValueError("Truncated BNK section")
        if name == b"BKHD":
            bkhd = data[pos:end]
        if name == b"HIRC":
            cursor = pos+12
            for _ in range(struct.unpack_from("<I", data, pos+8)[0]):
                typ = data[cursor]
                size, id = struct.unpack_from("<II", data, cursor+1)
                if size < 4 or cursor+5+size > end:
                    raise ValueError("Truncated HIRC object")
                nodes.append(dict(type=typ, id=id, raw=data[cursor:cursor+5+size]))
                cursor += 5+size
            if cursor != end:
                raise ValueError("Unexpected bytes in the HIRC object list")
        pos = end
    return bkhd, nodes


def load_banks(vfs):
    """Read only bank data; never load an entire multi-GB music stream."""
    banks = {}
    for pkg in vfs.packages():
        if not pkg.banks:
            continue
        print(f"Reading {len(pkg.banks)} banks: {pkg.entry['name']}", file=sys.stderr)
        buffer = vfs.read(pkg.entry) if len(pkg.banks)>1 and pkg.entry["length"]<128*1024*1024 else None
        for item in pkg.banks:
            data = buffer[item["offset"]:item["offset"]+item["length"]] if buffer is not None else pkg.read(item["offset"], item["length"])
            if data[:4] != b"BKHD":
                data = xor_audio(data, item["id"])
            if data[:4] != b"BKHD":
                raise ValueError(f"Failed to decode bank {item['id']}")
            # Whole-bank replacement preserves removals in a hotfix bank.
            banks[item["id"]] = (data, pkg.entry["name"])
    return banks


def tool_path(value, default):
    candidate = value or shutil.which(default)
    if not candidate or not Path(candidate).is_file():
        raise FileNotFoundError(f"Missing {default}; provide its path or install it from the official project")
    return str(Path(candidate).resolve())


def safe_stem(name):
    if not name or name in (".", "..") or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name[-1] in ". ":
        raise ValueError("Output labels must be plain file names without path separators")
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1,10)], *[f"LPT{i}" for i in range(1,10)]}:
        raise ValueError("Reserved Windows file name")
    if len(name) > 180:
        raise ValueError("Output label is too long")
    return name


def command(args):
    result = subprocess.run(args, capture_output=True, timeout=300)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-1800:])
    return result.stdout


def extract(vfs, media, out, formats=("wav", "mp3"), vgmstream=None, ffmpeg=None, overwrite=False):
    formats = set(formats)
    if not formats <= {"wem", "wav", "mp3"} or not formats:
        raise ValueError("Formats must be a combination of wem,wav,mp3")
    decoder = tool_path(vgmstream, "vgmstream-cli") if formats & {"wav", "mp3"} else None
    encoder = tool_path(ffmpeg, "ffmpeg") if "mp3" in formats else None
    names, ids = set(), set()
    for id, label in media:
        safe_stem(label)
        if id in ids or label.casefold() in names:
            raise ValueError("Repeated media ID or output label")
        ids.add(id); names.add(label.casefold())
    found = {}
    for pkg in vfs.packages():
        for item in pkg.sounds+pkg.externals:
            if item["id"] in ids:
                found[item["id"]] = (pkg, item)
    missing = ids-found.keys()
    if missing:
        raise ValueError(f"Media IDs absent from current audio stream indexes: {sorted(missing)}")
    records = []
    for id, label in media:
        pkg, item = found[id]
        wav_path = out/"WAV"/(label+".wav")
        mp3_path = out/"MP3"/(label+".mp3")
        wem_path = out/"original_wem"/(label+".wem")
        targets = [wem_path] + ([wav_path] if decoder else []) + ([mp3_path] if encoder else [])
        if not overwrite and any(p.exists() for p in targets):
            raise FileExistsError("Output exists; use another directory or explicitly pass --overwrite")
        for path in targets:
            path.parent.mkdir(parents=True, exist_ok=True)
        data = pkg.media(item)
        wem_path.write_bytes(data)
        record = dict(label=label, media_id=id, original_wem=str(wem_path),
                      source_package=pkg.entry["name"], source_chunk=str(vfs.chunk_path(pkg.entry)),
                      package_offset=pkg.entry["offset"], media_offset=item["offset"],
                      media_bytes=len(data), wem_sha256=hashlib.sha256(data).hexdigest())
        if decoder:
            command([decoder, "-i", "-o", str(wav_path), str(wem_path)])
            with wave.open(str(wav_path), "rb") as audio:
                record.update(wav=str(wav_path), sample_rate=audio.getframerate(), channels=audio.getnchannels(),
                              sample_width=audio.getsampwidth(), duration_seconds=audio.getnframes()/audio.getframerate())
        if encoder:
            command([encoder,"-nostdin","-hide_banner","-loglevel","error","-y","-i",str(wav_path),
                     "-c:a","libmp3lame","-b:a","320k","-id3v2_version","3","-metadata","title="+label,str(mp3_path)])
            record["mp3"] = str(mp3_path)
        records.append(record)
        save_json(out/"extraction_manifest.json", records)
        print(f"Extracted {id}: {label}", file=sys.stderr)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("index", "bank", "scan-banks", "extract"):
        p = sub.add_parser(action)
        p.add_argument("--game", required=True)
        p.add_argument("--out", required=True)
        if action == "bank":
            choice = p.add_mutually_exclusive_group(required=True)
            choice.add_argument("--event")
            choice.add_argument("--id", type=int)
        elif action == "scan-banks":
            p.add_argument("--contains-u32", action="append", type=int, required=True)
            p.add_argument("--match-all", action="store_true")
        elif action == "extract":
            p.add_argument("--media", action="append", required=True, help="MEDIA_ID=output_label")
            p.add_argument("--formats", default="wav,mp3")
            p.add_argument("--vgmstream")
            p.add_argument("--ffmpeg")
            p.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    out, vfs = prepare_output(args.out, args.game), AudioVFS(args.game)
    if args.action == "index":
        packages=[]
        for pkg in vfs.packages():
            packages.append(dict(**pkg.entry, source_chunk=str(vfs.chunk_path(pkg.entry)),
                                 banks=len(pkg.banks), sounds=len(pkg.sounds), externals=len(pkg.externals)))
        save_json(out/"audio_index.json", dict(blocks=vfs.summaries, packages=packages))
        print(json.dumps(dict(blocks=vfs.summaries, packages=len(packages)), ensure_ascii=False, indent=2))
    elif args.action == "extract":
        media=[]
        for spec in args.media:
            id, sep, label = spec.partition("=")
            if not sep:
                raise ValueError("--media must be MEDIA_ID=output_label")
            media.append((int(id), label))
        records=extract(vfs, media, out, args.formats.split(","), args.vgmstream, args.ffmpeg, args.overwrite)
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        banks=load_banks(vfs)
        if args.action == "bank":
            id=wwise_hash(args.event) if args.event else args.id
            if id not in banks:
                raise ValueError(f"Bank/event {id} not found. Check version or inspect the unsuffixed event name; then scan containing banks if needed.")
            data, package=banks[id]
            path=out/f"{id}.bnk";path.write_bytes(data)
            _, nodes=bank_nodes(data)
            report=dict(event=args.event,id=id,package=package,bank_path=str(path),
                        objects=[dict(type=n["type"],id=n["id"],data_hex=n["raw"][9:].hex()) for n in nodes])
            save_json(out/f"{id}_objects.json",report)
            print(json.dumps(report,ensure_ascii=False,indent=2))
        else:
            needles=[struct.pack("<I",value) for value in args.contains_u32]
            matches=[]
            for id,(data,package) in banks.items():
                present=[i for i,n in enumerate(needles) if n in data]
                if (len(present)==len(needles)) if args.match_all else bool(present):
                    path=out/f"{id}.bnk";path.write_bytes(data)
                    matches.append(dict(bank_id=id,package=package,path=str(path),
                                        matched_values=[args.contains_u32[i] for i in present]))
            save_json(out/"bank_matches.json",matches)
            print(json.dumps(matches,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError, struct.error, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(2)
