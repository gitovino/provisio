#!/usr/bin/env python3
"""Provisio — maakt de geneesmiddelenlijst voor de app (data/medicijnen.json).

Bron: de openbare export van SAM v2, de Authentieke Bron Geneesmiddelen
(FAGG, RIZIV, BCFI, FOD Volksgezondheid, eHealth). Die export is vrij te
downloaden, zonder account: https://www.vas.ehealth.fgov.be/websamcivics/samcivics/

Het script
  1. vraagt het nummer van de nieuwste volledige export op,
  2. downloadt die (een ZIP met XML-bestanden van enkele GB uitgepakt),
  3. leest alleen wat de app nodig heeft: streepjescode (GTIN), CNK-nummer,
     naam, werkzame stof, vorm, verpakking, voorschrift, ATC en bijsluiterlink,
  4. schrijft een compact JSON-bestand. Is de inhoud niet veranderd, dan blijft
     het bestaande bestand ongewijzigd (dus geen nieuwe commit).

Alleen de standaardbibliotheek van Python 3.9+ is nodig.

Gebruik:
  python scripts/sam_medicijnen.py --out data/medicijnen.json
  python scripts/sam_medicijnen.py --zip export.zip --out data/medicijnen.json   (eigen ZIP, om te testen)
"""
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

BASE = "https://www.vas.ehealth.fgov.be/websamcivics/samcivics/download"
UA = {"User-Agent": "Provisio-medicijnenlijst/1.0 (+https://github.com)"}
LANGS = ("Nl", "Fr", "En", "De")
KEEP_YEARS = 3  # ook dozen die tot 3 jaar geleden nog vergund waren: oude dozen in de kast blijven herkenbaar


# ---------- XML-hulpjes (namespaces negeren, alleen lokale namen) ----------
def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def child(el, name):
    if el is None:
        return None
    for c in el:
        if local(c.tag) == name:
            return c
    return None


def children(el, name):
    return [c for c in el if local(c.tag) == name] if el is not None else []


def txt(el, *path):
    """Tekst van een (eventueel meertalig) element; Nederlands eerst."""
    for name in path:
        el = child(el, name)
        if el is None:
            return ""
    for lang in LANGS:
        t = child(el, lang)
        if t is not None and t.text and t.text.strip():
            return t.text.strip()
    return el.text.strip() if el.text and el.text.strip() else ""


def pick_data(el, today, cutoff):
    """Het <Data>-blok dat vandaag geldt; anders het laatste dat nog na `cutoff` liep."""
    blocks = children(el, "Data")
    cur = [d for d in blocks if d.get("from", "0000") <= today and (not d.get("to") or d.get("to") >= today)]
    if cur:
        return cur[-1], True
    old = [d for d in blocks if d.get("to") and d.get("to") >= cutoff]
    if old:
        return max(old, key=lambda d: d.get("from", "")), False
    return None, False


def iter_top(fileobj, names):
    """Loopt de entiteiten op het eerste niveau af zonder het hele bestand in het geheugen te houden."""
    ctx = ET.iterparse(fileobj, events=("start", "end"))
    _, root = next(ctx)
    depth = 1
    for ev, el in ctx:
        if ev == "start":
            depth += 1
            continue
        depth -= 1
        if depth == 1:
            if local(el.tag) in names:
                yield local(el.tag), el
            root.clear()


# ---------- normaliseren, gelijk aan gtinToEan() in de app ----------
def norm_gtin(g):
    g = re.sub(r"\D", "", g or "")
    if not 8 <= len(g) <= 14:
        return ""
    g = g.zfill(14)
    if g.startswith("000000"):
        return g[6:]
    if g.startswith("0"):
        return g[1:]
    return g


def norm_cnk(c):
    c = re.sub(r"\D", "", c or "")
    return c.zfill(7) if 1 <= len(c) <= 7 else ""


def is_rx(code, descr):
    """1 = op voorschrift, 0 = zonder voorschrift, -1 = onbekend."""
    d = (descr or "").lower()
    if not d and not code:
        return -1
    if re.search(r"niet onderworpen|zonder|geen (medisch )?voorschrift|non soumis|sans prescription|not subject|vrij", d):
        return 0
    if "voorschrift" in d or "prescription" in d:
        return 1
    return -1


# ---------- download ----------
def latest_version(xsd):
    with urllib.request.urlopen(urllib.request.Request(f"{BASE}/samv2-full-getLastVersion?xsd={xsd}", headers=UA), timeout=120) as r:
        return r.read().decode().strip()


def download(xsd, dest):
    version = latest_version(xsd)
    url = f"{BASE}/samv2-download?type=FULL&xsd={xsd}&version={version}"
    print(f"SAM-export versie {version} downloaden…", flush=True)
    n = 0
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=3600) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            n += len(chunk)
    print(f"  {n / 1e6:.0f} MB gedownload", flush=True)
    return version


def find_member(z, prefix):
    for name in z.namelist():
        base = name.rsplit("/", 1)[-1]
        if base.startswith(prefix + "-") and base.endswith(".xml"):
            return name
    return None


# ---------- inlezen ----------
def read_vtm(z, today, cutoff):
    """Werkzame stof per virtueel product (VMP → VTM)."""
    vmp_vtm, vtm_name = {}, {}
    name = find_member(z, "VMP")
    if not name:
        print("  ! VMP-bestand niet gevonden: werkzame stof blijft leeg", flush=True)
        return {}
    with z.open(name) as f:
        for kind, el in iter_top(f, {"Vmp", "Vtm"}):
            d, _ = pick_data(el, today, cutoff)
            if d is None:
                continue
            if kind == "Vmp":
                vtm = child(d, "Vtm")
                if vtm is not None and vtm.get("code"):
                    vmp_vtm[el.get("code")] = vtm.get("code")
            else:
                vtm_name[el.get("code")] = txt(d, "Name")
    return {vmp: vtm_name.get(vtm, "") for vmp, vtm in vmp_vtm.items()}


def form_of(amp, today, cutoff):
    for comp in children(amp, "AmpComponent"):
        d, _ = pick_data(comp, today, cutoff)
        f = txt(d, "PharmaceuticalForm", "Name") if d is not None else ""
        if f:
            return f
    return ""


def gtins_of(ampp, ad):
    out = []
    for el in [ad, ampp]:
        if el is None:
            continue
        for k, v in el.attrib.items():
            if local(k).lower() == "gtin":
                out.append(v)
        for c in el:
            if local(c.tag).lower() == "gtin" and c.text:
                out.append(c.text)
    return sorted({g for g in (norm_gtin(x) for x in out) if g})


def cnk_of(ampp, today, cutoff):
    best = ""
    for dm in children(ampp, "Dmpp"):
        if dm.get("codeType", "CNK").upper() != "CNK":
            continue
        d, _ = pick_data(dm, today, cutoff)
        if d is None:
            continue
        c = norm_cnk(dm.get("code"))
        if not c:
            continue
        if dm.get("deliveryEnvironment", "P") == "P":
            return c
        best = best or c
    return best


def read_amp(z, today, cutoff, vtm_of):
    name = find_member(z, "AMP")
    if not name:
        sys.exit("AMP-bestand niet gevonden in de export.")
    rows, stats, sample = [], dict(amp=0, ampp=0, gtin=0, cnk=0, leaflet=0, rx=0, te_koop=0, zonder_code=0), None
    with z.open(name) as f:
        for _, amp in iter_top(f, {"Amp"}):
            d, _ = pick_data(amp, today, cutoff)
            if d is None:
                continue
            stats["amp"] += 1
            amp_name = txt(d, "Name") or txt(d, "OfficialName")
            subst = vtm_of.get(amp.get("vmpCode") or "", "")
            form = form_of(amp, today, cutoff)
            for ampp in children(amp, "Ampp"):
                ad, current = pick_data(ampp, today, cutoff)
                if ad is None:
                    continue
                if sample is None:
                    sample = sorted({local(c.tag) for c in ad})
                stats["ampp"] += 1
                gt, cnk = gtins_of(ampp, ad), cnk_of(ampp, today, cutoff)
                if not gt and not cnk:
                    stats["zonder_code"] += 1
                    continue
                comm, _ = pick_data(child(ampp, "Commercialization"), today, today) if child(ampp, "Commercialization") is not None else (None, False)
                te_koop = int(bool(current and comm is not None and comm.get("from", "0000") <= today and (not comm.get("to") or comm.get("to") >= today)))
                dm = child(ad, "DeliveryModus")
                afl = txt(ad, "DeliveryModus", "Description")
                rx = is_rx(dm.get("code") if dm is not None else "", afl)
                link = txt(ad, "LeafletLink")
                rows.append([",".join(gt), cnk, amp_name or txt(ad, "PrescriptionNameFamhp"), subst, form,
                             txt(ad, "PackDisplayValue"), rx, afl, (child(ad, "Atc").get("code") if child(ad, "Atc") is not None else "") or "",
                             link, te_koop])
                stats["gtin"] += bool(gt)
                stats["cnk"] += bool(cnk)
                stats["leaflet"] += bool(link)
                stats["rx"] += rx == 1
                stats["te_koop"] += te_koop
    return rows, stats, sample


def compact(rows):
    """Herhaalde stukken één keer bewaren: link-voorvoegsels en afleveringswijzen."""
    pre, pre_i, afl, afl_i = [], {}, [], {}

    def idx(table, index, v):
        if v not in index:
            index[v] = len(table)
            table.append(v)
        return index[v]

    out = []
    for r in sorted(rows, key=lambda r: (r[2].lower(), r[1], r[0])):
        link = r[9]
        if link:
            cut = link.rfind("/") + 1
            if "=" in link[cut:]:
                cut = link.rfind("=") + 1
            link = [idx(pre, pre_i, link[:cut]), link[cut:]]
        else:
            link = 0
        out.append([r[0], r[1], r[2], r[3], r[4], r[5], r[6], idx(afl, afl_i, r[7]) if r[7] else -1, r[8], link, r[10]])
    return out, pre, afl


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/medicijnen.json"))
    ap.add_argument("--xsd", type=int, default=6)
    ap.add_argument("--zip", type=pathlib.Path, help="Bestaande SAM-ZIP gebruiken in plaats van downloaden")
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="Peildatum (JJJJ-MM-DD)")
    a = ap.parse_args()
    today = a.date
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=365 * KEEP_YEARS)).isoformat()

    with tempfile.TemporaryDirectory() as tmp:
        if a.zip:
            zpath, version = a.zip, a.zip.stem
        else:
            zpath = pathlib.Path(tmp) / "sam.zip"
            version = download(a.xsd, zpath)
        with zipfile.ZipFile(zpath) as z:
            print("Werkzame stoffen lezen…", flush=True)
            vtm_of = read_vtm(z, today, cutoff)
            print("Verpakkingen lezen…", flush=True)
            rows, stats, sample = read_amp(z, today, cutoff, vtm_of)

    rijen, pre, afl = compact(rows)
    h = hashlib.sha256(json.dumps([rijen, pre, afl], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:16]
    print("Resultaat:", json.dumps(stats), flush=True)
    if stats["gtin"] == 0:
        print("  ! Geen enkele streepjescode (GTIN) gevonden. Velden in een verpakking:", sample, flush=True)
    if not rijen:
        sys.exit("Geen enkele verpakking gevonden: het bestand blijft ongewijzigd.")

    if a.out.exists():
        try:
            if json.loads(a.out.read_text(encoding="utf-8")).get("hash") == h:
                print(f"Inhoud ongewijzigd ({len(rijen)} verpakkingen): {a.out} blijft zoals het is.")
                return
        except Exception:
            pass
    doc = {
        "v": 1,
        "bron": "SAM v2 – Authentieke Bron Geneesmiddelen (FAGG, RIZIV, BCFI, FOD Volksgezondheid, eHealth). Hergebruik zonder officieel karakter.",
        "export": version, "datum": today, "aantal": len(rijen), "hash": h,
        "velden": ["gtin", "cnk", "naam", "stof", "vorm", "verpakking", "voorschrift", "afleverwijze", "atc", "bijsluiter", "te koop"],
        "pre": pre, "afl": afl, "rijen": rijen,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Geschreven: {a.out} · {len(rijen)} verpakkingen · {a.out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
