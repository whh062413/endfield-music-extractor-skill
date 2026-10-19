#!/usr/bin/env python3
"""Catalog music segments and their source media IDs using an official wwiser.pyz."""
import argparse
import json
import struct
import sys
from pathlib import Path

from endfield_audio import AudioVFS, bank_nodes, load_banks, prepare_output, save_json


def catalog(game, out, wwiser, durations=(), tolerance=2.0):
    wwiser = Path(wwiser).expanduser().resolve()
    if not wwiser.is_file():
        raise FileNotFoundError("Provide the official wwiser.pyz with --wwiser")
    vfs, merged, header, version = AudioVFS(game), {}, None, None
    for bank_id, (data, package) in load_banks(vfs).items():
        bkhd, nodes = bank_nodes(data)
        music = [n for n in nodes if n["type"] in (10, 11, 12, 13)]
        if not music:
            continue
        bank_version = struct.unpack_from("<I", bkhd, 8)[0]
        if version is not None and version != bank_version:
            raise ValueError("Music banks have different Wwise versions; parse them separately")
        header, version = bkhd, bank_version
        for node in music:
            node.update(bank_id=bank_id, package=package)
            merged[node["id"]] = node
    if not merged:
        raise ValueError("No Wwise music objects found in current audio banks")
    payload = struct.pack("<I", len(merged)) + b"".join(n["raw"] for n in merged.values())
    aggregate = out / "music_metadata.bnk"
    aggregate.write_bytes(header+b"HIRC"+struct.pack("<I", len(payload))+payload)
    sys.path.insert(0, str(wwiser))
    from wwiser.parser.wparser import Parser
    parser = Parser()
    parser.parse_banks([str(aggregate)])
    banks = parser.get_banks()
    if len(banks) != 1 or banks[0].get_error_count():
        raise ValueError("wwiser could not parse all music metadata; inspect its diagnostics")
    bank = banks[0]

    def values(node, name):
        return [field.value() for field in node.finds(name=name)]

    tracks = {}
    for node in bank.finds(name="CAkMusicTrack"):
        id = int(node.find1(name="ulID").value())
        tracks[id] = dict(track_id=id, source_ids=sorted(set(int(v) for v in values(node,"sourceID") if int(v)>0)),
                          source_durations_seconds=[float(v)/1000 for v in values(node,"fSrcDuration")],
                          clip_fields={name:values(node,name) for name in
                                       ("fPlayAt","fBeginTrimOffset","fEndTrimOffset","fSrcDuration")},
                          source_bank_id=merged[id]["bank_id"],source_package=merged[id]["package"])
    segments=[]
    for node in bank.finds(name="CAkMusicSegment"):
        id = int(node.find1(name="ulID").value())
        children = [int(v) for v in values(node,"ulChildID")]
        contained = [tracks[t] for t in children if t in tracks]
        segment = dict(segment_id=id, duration_seconds=float(node.find1(name="fDuration").value())/1000,
                       tracks=contained,source_ids=sorted({s for t in contained for s in t["source_ids"]}))
        segment["matching_durations"] = [d for d in durations if any(
            abs(d-candidate)<=tolerance for candidate in [segment["duration_seconds"]]+
            [length for t in contained for length in t["source_durations_seconds"]])]
        segments.append(segment)
    report=dict(wwise_version=version,segments=segments,track_count=len(tracks),
                candidates=[s for s in segments if not durations or s["matching_durations"]],
                query_durations_seconds=list(durations),tolerance_seconds=tolerance,
                note="Segment/clip metadata narrows candidates. Confirm media duration and sound before labeling a match.")
    save_json(out/"music_catalog.json",report)
    print(json.dumps(dict(segments=len(segments),tracks=len(tracks),candidates=len(report["candidates"]),
                          catalog=str(out/"music_catalog.json"),
                          first_candidates=[{k:s[k] for k in ("segment_id","duration_seconds","source_ids")}
                                            for s in report["candidates"][:15]]),
                     ensure_ascii=False,indent=2))


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game",required=True)
    parser.add_argument("--out",required=True)
    parser.add_argument("--wwiser",required=True)
    parser.add_argument("--duration",action="append",type=float,default=[])
    parser.add_argument("--tolerance",type=float,default=2.0)
    args=parser.parse_args()
    try:
        if args.tolerance<0 or any(d<=0 for d in args.duration):
            raise ValueError("Durations must be positive and tolerance non-negative")
        catalog(args.game,prepare_output(args.out,args.game),args.wwiser,args.duration,args.tolerance)
    except (ValueError,OSError,RuntimeError,ImportError) as error:
        print(f"ERROR: {error}",file=sys.stderr)
        sys.exit(2)
