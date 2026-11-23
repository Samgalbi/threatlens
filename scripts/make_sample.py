"""Build the small, committed sample in data/raw/sample/ from the full downloads.

The full dumps (55 MB ATT&CK...) are git-ignored; the sample lets anyone run the
pipeline and the tests in seconds.  Usage: python scripts/make_sample.py
"""

import csv
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

RAW = Path("data/raw")
OUT = RAW / "sample"
KEEP_TECHNIQUES = {
    "T1059",
    "T1059.001",
    "T1003",
    "T1003.001",
    "T1190",
    "T1566",
    "T1566.001",
    "T1539",
    "T1486",
    "T1071",
    "T1071.001",
    "T1547",
    "T1547.001",
    "T1110",
}


def sample_attack() -> None:
    src = next(RAW.glob("enterprise-attack*.json"))
    bundle = json.loads(src.read_text(encoding="utf-8"))
    objs = bundle["objects"]

    def ext(o: dict) -> str | None:
        return next(
            (
                r.get("external_id")
                for r in o.get("external_references", [])
                if r.get("source_name") == "mitre-attack"
            ),
            None,
        )

    keep = {o["id"] for o in objs if o["type"] == "attack-pattern" and ext(o) in KEEP_TECHNIQUES}
    rels = [o for o in objs if o["type"] == "relationship" and o.get("target_ref") in keep]
    rels = rels[:120]  # cap the procedure examples
    keep |= {r["source_ref"] for r in rels}
    collection = [
        {k: v for k, v in o.items() if k != "x_mitre_contents"}  # 26k refs, useless here
        for o in objs
        if o["type"] == "x-mitre-collection"
    ]
    kept = collection + [o for o in objs if o["id"] in keep] + rels
    bundle["objects"] = kept
    (OUT / src.name).write_text(json.dumps(bundle, indent=1), encoding="utf-8")
    print(f"ATT&CK sample: {len(kept)} objects")


def sample_capec() -> None:
    src = RAW / "stix-capec.json"
    if not src.exists():
        return
    bundle = json.loads(src.read_text(encoding="utf-8"))
    aps = [o for o in bundle["objects"] if o["type"] == "attack-pattern"][:40]
    bundle["objects"] = aps
    (OUT / src.name).write_text(json.dumps(bundle, indent=1), encoding="utf-8")
    print(f"CAPEC sample: {len(aps)} patterns")


def sample_cwe() -> None:
    files = list(RAW.glob("cwe/cwec*.xml"))
    if not files:
        print("CWE: not downloaded, skipped")
        return
    tree = ET.parse(files[0])
    root = tree.getroot()
    for container in root:
        if container.tag.endswith("Weaknesses"):
            for w in list(container)[40:]:
                container.remove(w)
        elif not container.tag.endswith("External_References"):
            root.remove(container)
    tree.write(OUT / files[0].name, encoding="utf-8", xml_declaration=True)
    print("CWE sample: 40 weaknesses")


def sample_ctibench() -> None:
    csv.field_size_limit(10**9)
    for src in sorted((RAW / "ctibench").glob("*.tsv")):
        with src.open(encoding="utf-8") as f:
            rows = list(csv.reader(f, delimiter="\t"))
        dest = OUT / "ctibench" / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", encoding="utf-8", newline="") as f:
            csv.writer(f, delimiter="\t").writerows(rows[:51])  # header + 50 rows
        print(f"CTIBench sample: {src.name} 50 rows")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    sample_attack()
    sample_capec()
    sample_cwe()
    sample_ctibench()
    return 0


if __name__ == "__main__":
    sys.exit(main())
