"""Download the frozen data sources into data/raw/ and write data/MANIFEST.json (sha256).

Usage:  python scripts/download_data.py [--only attack capec cwe ctibench]
"""

import argparse
import hashlib
import json
import logging
import sys
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("download")

RAW = Path("data/raw")
MANIFEST = Path("data/MANIFEST.json")
ATTACK_VERSION = "20.1"
CTIBENCH_BASE = "https://raw.githubusercontent.com/xashru/cti-bench/main/data"

SOURCES: dict[str, list[tuple[str, str]]] = {
    "attack": [
        (
            f"enterprise-attack-{ATTACK_VERSION}.json",
            "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/"
            f"enterprise-attack/enterprise-attack-{ATTACK_VERSION}.json",
        )
    ],
    "capec": [
        (
            "stix-capec.json",
            "https://raw.githubusercontent.com/mitre/cti/master/capec/2.1/stix-capec.json",
        )
    ],
    "cwe": [("cwec_latest.xml.zip", "https://cwe.mitre.org/data/xml/cwec_latest.xml.zip")],
    "ctibench": [
        (f"ctibench/{name}", f"{CTIBENCH_BASE}/{name}")
        for name in ("cti-rcm.tsv", "cti-rcm-2021.tsv", "cti-ate.tsv", "cti-mcq.tsv")
    ],
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "threatlens-ingest/0.2"})
    with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
        while block := resp.read(1 << 20):
            out.write(block)
    tmp.replace(dest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", choices=sorted(SOURCES), default=sorted(SOURCES))
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    failures = 0
    for key in args.only:
        for filename, url in SOURCES[key]:
            dest = RAW / filename
            try:
                logger.info("Downloading %s", url)
                fetch(url, dest)
            except Exception as exc:  # network errors must not stop the other sources
                failures += 1
                logger.error("FAILED %s: %s", url, exc)
                continue
            entry: dict[str, object] = {
                "url": url,
                "sha256": sha256(dest),
                "bytes": dest.stat().st_size,
                "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            if dest.suffix == ".zip":
                with zipfile.ZipFile(dest) as zf:
                    members = [m for m in zf.namelist() if m.endswith(".xml")]
                    zf.extractall(RAW / "cwe")
                entry["extracted"] = [f"cwe/{m}" for m in members]
            manifest[filename] = entry
            logger.info("OK %s (%.1f MB)", filename, dest.stat().st_size / 1e6)

    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Manifest written to %s", MANIFEST)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
