import argparse
import calendar
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
API = "https://export.arxiv.org/api/query"
MONTHS = ("2025-01", "2025-02", "2025-03")
DATA_DIR = ROOT / "data"
PAGE_SIZE = 200
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "os": "http://a9.com/-/spec/opensearch/1.1/",
}


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_feed(content):
    root = ET.fromstring(content)
    rows = []
    for entry in root.findall("atom:entry", NS):
        value = lambda key: clean(entry.findtext(key, default="", namespaces=NS))
        identifier = value("atom:id")
        assert "api/errors" not in identifier, value("atom:summary")
        versioned_id = identifier.split("/abs/")[-1]
        match = re.search(r"v(\d+)$", versioned_id)
        primary = entry.find("arxiv:primary_category", NS)
        rows.append({
            "arxiv_id": re.sub(r"v\d+$", "", versioned_id),
            "versioned_id": versioned_id,
            "version": int(match.group(1)) if match else None,
            "title": value("atom:title"),
            "abstract": value("atom:summary"),
            "authors": [clean(a.findtext("atom:name", "", NS))
                        for a in entry.findall("atom:author", NS)],
            "categories": [c.get("term") for c in entry.findall("atom:category", NS)],
            "primary_category": primary.get("term") if primary is not None else None,
            "published": value("atom:published"),
            "updated": value("atom:updated"),
            "doi": value("arxiv:doi") or None,
            "journal_ref": value("arxiv:journal_ref") or None,
            "comment": value("arxiv:comment") or None,
            "abs_url": f"https://arxiv.org/abs/{versioned_id}",
            "pdf_url": next((link.get("href", "").replace("http://", "https://")
                             for link in entry.findall("atom:link", NS)
                             if link.get("title") == "pdf"), None),
        })
    return rows, int(root.findtext("os:totalResults", "0", NS))


def month_config(month, data_dir):
    first = datetime.strptime(month, "%Y-%m")
    last = calendar.monthrange(first.year, first.month)[1]
    query = (f"(cat:cs.IR OR cat:cs.CL) AND submittedDate:"
             f"[{first:%Y%m}010000 TO {first:%Y%m}{last:02d}2359]")
    raw_dir = data_dir / "raw" if month == "2025-01" else data_dir / "raw" / month
    name = "collection_manifest.json" if month == "2025-01" else f"collection_manifest_{month}.json"
    return query, raw_dir, data_dir / name


def page_path(data_dir, page):
    relative = Path(page["file"])
    if relative.parts[0] == "data":
        relative = Path(*relative.parts[1:])
    assert not relative.is_absolute() and ".." not in relative.parts
    return data_dir / relative


def validate_records(records, month, total):
    ids = [row["arxiv_id"] for row in records]
    assert len(records) == total and len(ids) == len(set(ids))
    first = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
    next_month = (first.replace(year=first.year + 1, month=1) if first.month == 12
                  else first.replace(month=first.month + 1))
    dates = [datetime.fromisoformat(row["published"].replace("Z", "+00:00")) for row in records]
    assert dates == sorted(dates) and all(first <= date < next_month for date in dates)
    assert all(set(row["categories"]) & {"cs.IR", "cs.CL"} for row in records)


def load_month(month, data_dir=DATA_DIR):
    data_dir = Path(data_dir)
    query, _, manifest_path = month_config(month, data_dir)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["search_query"] == query
    records, expected_start = [], 0
    for page in manifest["pages"]:
        payload = page_path(data_dir, page).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == page["sha256"]
        rows, total = parse_feed(payload)
        assert page["start"] == expected_start and len(rows) == page["entries"]
        assert total == manifest["reported_total"]
        records.extend(rows)
        expected_start += len(rows)
    validate_records(records, month, manifest["reported_total"])
    assert len(records) == manifest["collected"]
    return records, manifest


def load_dataset(data_dir=DATA_DIR, months=MONTHS):
    data_dir = Path(data_dir)
    records, audit = [], []
    for month in months:
        rows, manifest = load_month(month, data_dir)
        records.extend(rows)
        audit.append({"Месяц": month, "Статей": len(rows), "Страниц API": len(manifest["pages"]),
                      "XML, МиБ": sum(page_path(data_dir, p).stat().st_size
                                      for p in manifest["pages"]) / 1024**2,
                      "Получено, UTC": manifest["collection_finished_at_utc"]})
    assert len({r["arxiv_id"] for r in records}) == len(records)
    return records, audit


class ArxivClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "ResearchAssistantEDA/1.0 (https://github.com/Novart-projects/research-assistant)"
        )
        self.last_request = 0.0

    def fetch(self, params):
        for attempt in range(3):
            time.sleep(max(0, 3.2 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            response = self.session.get(API, params=params, timeout=(15, 90))
            if response.status_code >= 500 and attempt < 2:
                time.sleep(10 * (attempt + 1))
                continue
            response.raise_for_status()
            return response.content, response.url


def collect_month(month, data_dir, client):
    query, raw_dir, manifest_path = month_config(month, data_dir)
    if manifest_path.exists():
        rows, _ = load_month(month, data_dir)
        print(f"{month}: cache verified ({len(rows)} articles)", flush=True)
        return
    raw_dir.mkdir(parents=True, exist_ok=True)
    pages, records, start, total = [], [], 0, None
    while total is None or start < total:
        params = dict(search_query=query, start=start, max_results=PAGE_SIZE,
                      sortBy="submittedDate", sortOrder="ascending")
        path = raw_dir / f"arxiv_{start:05d}.xml"
        if path.exists():
            body = path.read_bytes()
            url = requests.Request("GET", API, params=params).prepare().url
            fetched_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        else:
            body, url = client.fetch(params)
            parse_feed(body)
            temporary = path.with_suffix(".xml.part")
            temporary.write_bytes(body)
            temporary.replace(path)
            fetched_at = datetime.now(timezone.utc).isoformat()
        rows, observed_total = parse_feed(body)
        assert total is None or observed_total == total
        total = observed_total
        assert total <= 10000
        assert rows or start >= total
        records.extend(rows)
        pages.append({"file": str(path.relative_to(data_dir)), "start": start,
                      "entries": len(rows), "reported_total": total, "url": url,
                      "fetched_at_utc": fetched_at, "sha256": hashlib.sha256(body).hexdigest()})
        print(f"{month}: collected {len(records)}/{total}", flush=True)
        start += len(rows)
    validate_records(records, month, total)
    manifest = {
        "source": API, "search_query": query, "sort_by": "submittedDate", "sort_order": "ascending",
        "page_size": PAGE_SIZE, "reported_total": total, "collected": len(records), "pages": pages,
        "collection_finished_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    temporary = manifest_path.with_suffix(".json.part")
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(manifest_path)
    load_month(month, data_dir)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", choices=MONTHS, help="Collect one month; by default collect the full quarter.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="Local cache directory (default: data/).")
    parser.add_argument("--offline", action="store_true", help="Validate cached data without network access.")
    args = parser.parse_args()
    months = (args.month,) if args.month else MONTHS
    data_dir = args.data_dir.resolve()
    if not args.offline:
        client = ArxivClient()
        for month in months:
            collect_month(month, data_dir, client)
    records, _ = load_dataset(data_dir, months)
    print(f"Ready: {len(records)} articles in {data_dir}")


if __name__ == "__main__":
    main()
