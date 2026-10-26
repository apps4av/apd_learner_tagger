# Download the current FAA airport diagrams and write avare_aptdiags.php,
# the 13-field geotag file tpp reads:
#   faaid,tfwA,tfwB,tfwC,tfwD,tfwE,tfwF,wftA,wftB,wftC,wftD,wftE,wftF

import os
import re
import shutil
import subprocess
import urllib.request
import xml.etree.ElementTree as et
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import cycle
from read_arpt_dgm_png import ArptDgmPng, _csv_line

FAA_PAGE = "https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/dtpp/"
LEARNT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ReadArptDgmPng_learnt.csv")
WORK = os.environ.get("WORK", "/tmp/dtpp")
OUT = os.environ.get("OUT", "/out")
WORKERS = int(os.environ.get("WORKERS", "4"))

GS = [
    "gs", "-q", "-dQuiet", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dNOPROMT",
    "-dMaxBitmap=500000000", "-dAlignToPixels=0", "-dGridFitTT=2",
    "-sDEVICE=pngalpha", "-dTextAlphaBits=4", "-dGraphicsAlphaBits=4",
    "-r300x300", "-dFirstPage=1", "-dLastPage=1",
]


def _open(url):
    req = urllib.request.Request(url, headers={"User-Agent": "apd-learner-tagger"})
    return urllib.request.urlopen(req, timeout=120)


def chart_urls(stamp):
    pattern = re.compile(r"^http.*DDTPP[A-E]+_" + re.escape(stamp) + r"\.zip$")
    html = _open(FAA_PAGE).read().decode("utf-8", "replace")
    found = set()
    for href in re.findall(r'href="([^"]+)"', html):
        if pattern.search(href):
            found.add(href)
    if not found:
        raise RuntimeError("no d-TPP zips for " + stamp)
    return sorted(found)


def download_charts(urls):
    os.makedirs(WORK, exist_ok=True)
    for url in urls:
        name = os.path.join(WORK, url.rsplit("/", 1)[-1])
        if not os.path.isfile(name):
            print("downloading", url, flush=True)
            with _open(url) as src, open(name, "wb") as dst:
                shutil.copyfileobj(src, dst)
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(name) as zf:
                zf.extractall(WORK)
    for name in os.listdir(WORK):
        if name.lower().endswith(".pdf") and name != name.upper():
            os.rename(os.path.join(WORK, name), os.path.join(WORK, name.upper()))


def apd_jobs():
    root = et.parse(os.path.join(WORK, "d-TPP_Metafile.xml")).getroot()
    jobs = []
    seen = set()
    for airport in root.iter("airport_name"):
        faa = airport.get("apt_ident")
        if not faa or faa in seen:
            continue
        icao = airport.get("icao_ident") or faa
        chosen = None
        for record in airport.findall("record"):
            if (record.findtext("chart_code") or "").upper() != "APD":
                continue
            pdf = (record.findtext("pdf_name") or "").upper()
            if not pdf:
                continue
            chosen = pdf
            if (record.findtext("chart_name") or "").upper().startswith("AIRPORT DIAGRAM"):
                break
        if chosen:
            jobs.append((faa, icao, chosen))
            seen.add(faa)
    return jobs


def tag_one(job):
    faa, icao, pdf = job
    pdf_path = os.path.join(WORK, pdf)
    png = os.path.join(WORK, "apd_" + faa + ".png")
    try:
        if not os.path.isfile(pdf_path):
            return faa, None, "missing " + pdf
        subprocess.check_call(GS + ["-sOutputFile=" + png, pdf_path],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        tfw, wft = ArptDgmPng(png, icao, LEARNT).process()
        return faa, _csv_line(faa, tfw, wft), None
    except Exception as e:
        return faa, None, str(e) or type(e).__name__
    finally:
        try:
            os.remove(png)
        except FileNotFoundError:
            pass


def main():
    if not os.path.isfile(LEARNT):
        raise SystemExit("missing " + LEARNT)
    stamp = cycle.get_version_start(cycle.get_cycle_download()).replace("-", "")[2:]
    download_charts(chart_urls(stamp))
    jobs = apd_jobs()
    print("tagging", len(jobs), "airport diagrams", flush=True)

    lines = []
    failed = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(tag_one, job) for job in jobs]
        done = 0
        for future in as_completed(futures):
            faa, line, error = future.result()
            done += 1
            if line:
                lines.append(line)
            else:
                failed += 1
                print("skip", faa + ":", error, flush=True)
            if done % 25 == 0 or done == len(jobs):
                print("tagged %d/%d" % (done, len(jobs)), flush=True)

    if not lines:
        raise SystemExit("no airport diagrams were tagged")

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "avare_aptdiags.php")
    with open(path, "w") as f:
        for line in sorted(lines):
            f.write(line + "\n")
    print("wrote", path, "airports", len(lines), "skipped", failed, flush=True)


if __name__ == "__main__":
    main()
