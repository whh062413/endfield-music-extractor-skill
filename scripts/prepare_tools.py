#!/usr/bin/env python3
"""Download pinned official wwiser/vgmstream helpers into a user-chosen work directory."""
import argparse
import hashlib
import io
import json
import os
import platform
import sys
import urllib.request
import zipfile
from pathlib import Path


def download(url):
    last=None
    for _ in range(3):
        try:
            request=urllib.request.Request(url,headers={"User-Agent":"EndfieldMusicExtractor/1.0"})
            with urllib.request.urlopen(request,timeout=30) as response:
                return response.read()
        except OSError as error:
            last=error
    raise RuntimeError(f"Official download failed: {url}: {last}")


def prepare(out):
    out=Path(out).expanduser().resolve();out.mkdir(parents=True,exist_ok=True)
    wwiser=out/"wwiser.pyz"
    if wwiser.exists():
        raise FileExistsError("Choose an empty tools directory; existing tools are not replaced")
    system=platform.system()
    if system not in ("Windows","Linux"):
        raise ValueError("This helper downloads Windows/Linux builds; obtain the official build for your platform manually")
    urls={"wwiser":"https://github.com/bnnm/wwiser/releases/download/v20260808/wwiser.pyz",
          "vgmstream":"https://github.com/vgmstream/vgmstream/releases/download/r2117/vgmstream-"+
                      ("win64.zip" if system=="Windows" else "linux.zip")}
    files={key:download(url) for key,url in urls.items()}
    # Both pyz and the binary release are ZIP archives; check before writing.
    for data in files.values():
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise ValueError("Official download did not contain a ZIP archive")
    folder=out/"vgmstream"
    folder.mkdir(exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(files["vgmstream"])) as archive:
        for info in archive.infolist():
            target=(folder/info.filename).resolve()
            if not target.is_relative_to(folder) or "\\" in info.filename:
                raise ValueError("Unsafe archive member path")
            if target.exists() and not info.is_dir():
                raise FileExistsError(f"Tool file already exists: {target}")
        archive.extractall(folder)
    wwiser.write_bytes(files["wwiser"])
    if system=="Linux":
        for path in folder.rglob("vgmstream-cli"):
            path.chmod(path.stat().st_mode|0o111)
    report={key:dict(url=urls[key],sha256=hashlib.sha256(data).hexdigest()) for key,data in files.items()}
    report["wwiser_path"]=str(wwiser)
    report["vgmstream_candidates"]=[str(p) for p in folder.rglob("vgmstream-cli*") if p.is_file()]
    (out/"tool_sources.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",required=True)
    args=parser.parse_args()
    try:
        prepare(args.out)
    except (ValueError,OSError,RuntimeError,zipfile.BadZipFile) as error:
        print(f"ERROR: {error}",file=sys.stderr)
        sys.exit(2)
