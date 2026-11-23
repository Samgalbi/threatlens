from pathlib import Path

from app.ingestion.parsers import load_stix_objects, parse_attack, parse_capec, parse_cwe

CWE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Weakness_Catalog xmlns="http://cwe.mitre.org/cwe-7" Name="CWE" Version="9.9" Date="2026-01-01">
  <Weaknesses>
    <Weakness ID="79" Name="Improper Neutralization of Input During Web Page Generation"
              Abstraction="Base" Status="Stable">
      <Description>The product does not neutralize user-controllable input.</Description>
      <Extended_Description><xhtml:p xmlns:xhtml="http://www.w3.org/1999/xhtml">XSS details.</xhtml:p>
      </Extended_Description>
    </Weakness>
    <Weakness ID="1" Name="Old" Status="Deprecated"><Description>gone</Description></Weakness>
  </Weaknesses>
</Weakness_Catalog>
"""


def test_parse_attack_sample(sample_dir: Path) -> None:
    objects = load_stix_objects(next(sample_dir.glob("enterprise-attack*.json")))
    docs = list(parse_attack(objects))
    ids = {d.external_id for d in docs if d.category == "technique"}
    assert "T1059.001" in ids
    ps = next(d for d in docs if d.external_id == "T1059.001" and d.category == "technique")
    assert ps.tactics == ["execution"] and ps.is_subtechnique
    assert ps.source == "mitre-attack-enterprise v20.1"
    assert "(Citation:" not in ps.text
    procedures = [d for d in docs if d.category == "procedure"]
    assert procedures and all(d.external_id.startswith("T") for d in procedures)


def test_parse_capec_sample_links_cwe(sample_dir: Path) -> None:
    docs = list(parse_capec(load_stix_objects(sample_dir / "stix-capec.json")))
    assert docs and all(d.external_id.startswith("CAPEC-") for d in docs)
    assert any(r.startswith("CWE-") for d in docs for r in d.related_ids)


def test_parse_cwe_skips_deprecated(tmp_path: Path) -> None:
    path = tmp_path / "cwec_test.xml"
    path.write_text(CWE_XML, encoding="utf-8")
    docs = list(parse_cwe(path))
    assert [d.external_id for d in docs] == ["CWE-79"]
    assert docs[0].source == "cwe v9.9"
    assert "XSS details." in docs[0].text
