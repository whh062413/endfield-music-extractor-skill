#!/usr/bin/env python3
"""Fetch short public Bilibili references or compare user-provided audio with local extracts."""
import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from endfield_audio import command, save_json, tool_path


def fetch_reference(url, out, ffmpeg, seconds=90):
    parsed=urllib.parse.urlparse(url)
    parts=parsed.path.strip("/").split("/")
    if parsed.scheme not in ("https","http") or parsed.hostname not in ("www.bilibili.com","bilibili.com") or len(parts)<2 or parts[0]!="video":
        raise ValueError("Provide a standard public https://www.bilibili.com/video/BV.../?p=N link")
    bvid=parts[1]
    if len(bvid)!=12 or not bvid.startswith("BV") or not bvid.isalnum():
        raise ValueError("Invalid Bilibili BV identifier")
    page=int(urllib.parse.parse_qs(parsed.query).get("p",["1"])[0])
    if page<1 or not 5<=seconds<=120:
        raise ValueError("Page must be positive; reference length must be 5–120 seconds")
    canonical=f"https://www.bilibili.com/video/{bvid}/?p={page}"

    def get_json(api):
        request=urllib.request.Request(api,headers={"User-Agent":"Mozilla/5.0","Referer":canonical})
        with urllib.request.urlopen(request,timeout=25) as response:
            value=json.load(response)
        if value.get("code")!=0:
            raise ValueError(f"Public video API returned {value.get('code')}: {value.get('message')}. Use an accessible user-provided audio reference instead.")
        return value["data"]

    video=get_json("https://api.bilibili.com/x/web-interface/view?bvid="+bvid)
    chosen=next((p for p in video["pages"] if p["page"]==page),None)
    if chosen is None:
        raise ValueError("Requested video part does not exist")
    stream=get_json(f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={chosen['cid']}&qn=16&fnval=16&fourk=0")
    audio=(stream.get("dash") or {}).get("audio") or []
    if not audio:
        raise ValueError("No public DASH audio stream is available; provide a local reference clip")
    address=max(audio,key=lambda a:a.get("bandwidth",0))["baseUrl"]
    if urllib.parse.urlparse(address).scheme not in ("http","https"):
        raise ValueError("Unsupported reference audio URL scheme")
    out=Path(out).expanduser().resolve();out.mkdir(parents=True,exist_ok=True)
    path=out/f"{bvid}_p{page}_reference.wav"
    if path.exists():
        raise FileExistsError(f"Reference already exists: {path}")
    decoder=tool_path(ffmpeg,"ffmpeg")
    command([decoder,"-nostdin","-hide_banner","-loglevel","error","-n","-user_agent","Mozilla/5.0",
             "-referer",canonical,"-i",address,"-t",str(seconds),"-vn","-ac","1","-ar","11025",
             "-c:a","pcm_s16le",str(path)])
    metadata=dict(source_url=canonical,title=video["title"],description=video.get("desc",""),
                  published_unix=video.get("pubdate"),page=page,part_title=chosen["part"],
                  video_duration_seconds=chosen["duration"],reference_file=str(path),
                  maximum_reference_seconds=seconds)
    save_json(path.with_suffix(".json"),metadata)
    print(json.dumps(metadata,ensure_ascii=False,indent=2))


def decode_mono(path, ffmpeg, rate):
    data=command([ffmpeg,"-nostdin","-hide_banner","-loglevel","error","-i",str(path),
                  "-vn","-ac","1","-ar",str(rate),"-f","f32le","pipe:1"])
    return np.frombuffer(data,dtype="<f4").astype(np.float64)


def waveform_score(local, reference, rate=11025, reference_start=5.0, seconds=60.0):
    start=int(rate*reference_start)
    y=reference[start:start+int(rate*seconds)]
    if len(y)<rate*5:
        raise ValueError("At least five seconds of nonempty reference audio are required after the chosen start")
    if len(local)<len(y):
        raise ValueError("Candidate is shorter than the selected reference window")
    y=y-y.mean()
    reference_energy=float(np.dot(y,y))
    if reference_energy<1e-12:
        raise ValueError("Reference window is silent")
    n,m=len(local),len(y)
    fft_size=1<<((n+m-2).bit_length())
    correlation=np.fft.irfft(np.fft.rfft(local,fft_size)*np.fft.rfft(y[::-1],fft_size),fft_size)[m-1:n]
    sums=np.concatenate(([0.0],np.cumsum(local)))
    squares=np.concatenate(([0.0],np.cumsum(local*local)))
    energy=(squares[m:]-squares[:-m])-(sums[m:]-sums[:-m])**2/m
    scores=correlation/np.sqrt(np.maximum(energy*reference_energy,1e-30))
    best=int(np.argmax(scores))
    return dict(normalized_waveform_correlation=float(np.clip(scores[best],-1,1)),
                alignment_seconds=best/rate-reference_start,seconds_compared=m/rate,
                reference_start_seconds=reference_start,
                note="Correlation measures this window's waveform similarity; it is not an identification probability.")


def compare(locals, references, out, ffmpeg, start, seconds):
    decoder=tool_path(ffmpeg,"ffmpeg")
    refs={str(Path(p).resolve()):decode_mono(p,decoder,11025) for p in references}
    results=[]
    for local_path in locals:
        local=decode_mono(local_path,decoder,11025)
        for path,reference in refs.items():
            pair=dict(local_file=str(Path(local_path).resolve()),reference_file=path)
            try:
                pair.update(waveform_score(local,reference,reference_start=start,seconds=seconds))
            except ValueError as error:
                pair["error"]=str(error)
            results.append(pair)
    out=Path(out).expanduser().resolve();out.parent.mkdir(parents=True,exist_ok=True)
    save_json(out,results)
    print(json.dumps(results,ensure_ascii=False,indent=2))
    if not any("normalized_waveform_correlation" in pair for pair in results):
        raise ValueError("No candidate/reference pair could be compared; inspect the saved report")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="action",required=True)
    fetch=sub.add_parser("reference")
    fetch.add_argument("--url",required=True)
    fetch.add_argument("--out",required=True)
    fetch.add_argument("--ffmpeg")
    fetch.add_argument("--seconds",type=float,default=90)
    match=sub.add_parser("compare")
    match.add_argument("--local",action="append",required=True)
    match.add_argument("--reference",action="append",required=True)
    match.add_argument("--out",required=True)
    match.add_argument("--ffmpeg")
    match.add_argument("--reference-start",type=float,default=5)
    match.add_argument("--seconds",type=float,default=60)
    args=parser.parse_args()
    try:
        if args.action=="reference":
            fetch_reference(args.url,args.out,args.ffmpeg,args.seconds)
        else:
            if args.reference_start<0 or args.seconds<=0:
                raise ValueError("Reference start must be non-negative and comparison length positive")
            compare(args.local,args.reference,args.out,args.ffmpeg,args.reference_start,args.seconds)
    except (ValueError,OSError,RuntimeError,subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}",file=sys.stderr)
        sys.exit(2)
