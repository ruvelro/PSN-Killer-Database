#!/usr/bin/env python3
import csv
import hashlib
import io
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "data")
PENDING_DIR = os.path.join(DATA_DIR, "pending")
MANIFEST_PATH = os.path.join(DATA_DIR, "catalog_manifest.json")

NPS_BASE_URL = "https://nopaystation.com/tsv"
VITAWIKI_BASE_URL = "https://vitawiki.xyz/free"

CATALOGS = [
    "PS3_GAMES.tsv",
    "PS3_UPDATES.tsv",
    "PS3_DEMOS.tsv",
    "PS3_THEMES.tsv",
    "PS3_AVATARS.tsv",
    "PS3_DLCS.tsv",
    "PSP_GAMES.tsv",
    "PSP_UPDATES.tsv",
    "PSP_DEMOS.tsv",
    "PSP_THEMES.tsv",
    "PSP_DLCS.tsv",
    "PSV_GAMES.tsv",
    "PSV_UPDATES.tsv",
    "PSV_DEMOS.tsv",
    "PSV_THEMES.tsv",
    "PSV_DLCS.tsv",
    "PSX_GAMES.tsv",
    "PSM_GAMES.tsv",
]

LEGACY_PS3_UPDATE_HEADER = ["Title ID", "Name", "Update Version", "PKG direct link"]
USER_AGENT = "Mozilla/5.0"


def source_name(base_url, file_name):
    if base_url == VITAWIKI_BASE_URL and file_name == "PSX_GAMES.tsv":
        return "PS1_GAMES.tsv"
    return file_name


def fetch_url(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8-sig", errors="replace")


def read_text(path):
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        return handle.read()


def has_header(first_row):
    return bool(first_row) and first_row[0].strip().lower() in {"title id", "id", "title_id"}


def parse_tsv(text, file_name):
    if not text.strip():
        return [], []
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    first = next(reader, None)
    if first is None:
        return [], []
    if has_header(first):
        header = [cell.strip() for cell in first]
        rows = [dict(zip(header, row + [""] * max(0, len(header) - len(row)))) for row in reader]
        return header, rows
    if file_name == "PS3_UPDATES.tsv":
        rows = []
        for row in [first, *reader]:
            if not row:
                continue
            padded = row + [""] * max(0, len(LEGACY_PS3_UPDATE_HEADER) - len(row))
            rows.append(dict(zip(LEGACY_PS3_UPDATE_HEADER, padded)))
        return [], rows
    return [], []


def clean(value):
    return (value or "").strip()


def is_missing(value):
    return clean(value).upper() in {"", "MISSING", "N/A", "NA"}


def is_url(value):
    return clean(value).lower().startswith(("http://", "https://"))


def first_value(row, *names):
    lowered = {key.lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None:
            return clean(value)
    return ""


def pkg_url(row):
    for key in row:
        lowered = key.lower()
        if "pkg direct link" == lowered or "update url" == lowered or "download url" == lowered:
            return clean(row.get(key))
    for key, value in row.items():
        lowered = key.lower()
        if "url" in lowered or "link" in lowered:
            if is_url(value):
                return clean(value)
    return ""


def infer_update_version(row):
    explicit = first_value(row, "Update Version", "Version")
    if explicit:
        return explicit if explicit.lower().startswith("v") else f"v{explicit}"
    candidates = [
        first_value(row, "Name"),
        first_value(row, "Content ID"),
        pkg_url(row),
    ]
    for text in candidates:
        match = re.search(r"[-_]A(\d{2})(\d{2})[-_]", text, flags=re.IGNORECASE)
        if match:
            return f"v{int(match.group(1)):02d}.{int(match.group(2)):02d}"
        match = re.search(r"v?(\d{1,2})[._](\d{1,2})", text, flags=re.IGNORECASE)
        if match:
            return f"v{int(match.group(1)):02d}.{int(match.group(2)):02d}"
    return "v01.00"


def normalized_key(row):
    content_id = first_value(row, "Content ID")
    url = pkg_url(row)
    if content_id:
        return ("content_id_url", content_id, url) if is_url(url) else ("content_id_missing", content_id)
    if is_url(url):
        return ("url", url)
    title_id = first_value(row, "Title ID", "ID")
    region = first_value(row, "Region")
    name = re.sub(r"\s+", " ", first_value(row, "Name")).casefold()
    version = first_value(row, "Update Version", "Version")
    return ("fallback", title_id, region, name, version, first_value(row, "RAP", "zRIF"))


def content_id_with_url(row):
    content_id = first_value(row, "Content ID")
    return content_id if content_id and is_url(pkg_url(row)) else ""


def compact_missing_duplicates(rows):
    content_ids_with_url = {content_id_with_url(row) for row in rows if content_id_with_url(row)}
    compacted = []
    key_to_index = {}
    for row in rows:
        content_id = first_value(row, "Content ID")
        if content_id and not is_url(pkg_url(row)) and content_id in content_ids_with_url:
            continue
        key = normalized_key(row)
        existing_index = key_to_index.get(key)
        if existing_index is None:
            key_to_index[key] = len(compacted)
            compacted.append(row)
        elif usefulness(row) > usefulness(compacted[existing_index]):
            compacted[existing_index] = {**compacted[existing_index], **{k: v for k, v in row.items() if not is_missing(v)}}
    return compacted


def usefulness(row):
    score = 0
    score += 100 if is_url(pkg_url(row)) else 0
    score += 30 if not is_missing(first_value(row, "RAP", "zRIF")) else 0
    score += 20 if not is_missing(first_value(row, "SHA256")) else 0
    score += 10 if not is_missing(first_value(row, "File Size", "Size")) else 0
    score += 5 if not is_missing(first_value(row, "Last Modification Date")) else 0
    score += sum(1 for value in row.values() if not is_missing(value))
    return score


def normalize_for_file(row, file_name):
    if file_name == "PS3_UPDATES.tsv":
        return {
            "Title ID": first_value(row, "Title ID", "ID"),
            "Name": first_value(row, "Name") or f"Actualización ({first_value(row, 'Title ID', 'ID')})",
            "Update Version": infer_update_version(row),
            "PKG direct link": pkg_url(row),
        }
    return row


def merge_rows(current_rows, incoming_rows, file_name):
    merged = compact_missing_duplicates([normalize_for_file(row, file_name) for row in current_rows])
    key_to_index = {normalized_key(row): index for index, row in enumerate(merged)}
    content_ids_with_url = {content_id_with_url(row) for row in merged if content_id_with_url(row)}

    added = 0
    improved = 0
    for row in incoming_rows:
        normalized = normalize_for_file(row, file_name)
        content_id = first_value(normalized, "Content ID")
        if content_id and not is_url(pkg_url(normalized)) and content_id in content_ids_with_url:
            continue
        key = normalized_key(normalized)
        existing_index = key_to_index.get(key)
        if existing_index is None:
            merged.append(normalized)
            key_to_index[key] = len(merged) - 1
            cid_with_url = content_id_with_url(normalized)
            if cid_with_url:
                content_ids_with_url.add(cid_with_url)
            added += 1
            continue
        if usefulness(normalized) > usefulness(merged[existing_index]):
            merged[existing_index] = {**merged[existing_index], **{k: v for k, v in normalized.items() if not is_missing(v)}}
            cid_with_url = content_id_with_url(merged[existing_index])
            if cid_with_url:
                content_ids_with_url.add(cid_with_url)
            improved += 1
    return compact_missing_duplicates(merged), added, improved


def write_tsv(path, header, rows, file_name):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        if file_name == "PS3_UPDATES.tsv":
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            for row in rows:
                writer.writerow([row.get(column, "") for column in LEGACY_PS3_UPDATE_HEADER])
            return
        final_header = header[:]
        seen = {name.lower() for name in final_header}
        for row in rows:
            for key in row:
                if key.lower() not in seen:
                    final_header.append(key)
                    seen.add(key.lower())
        writer = csv.DictWriter(handle, fieldnames=final_header, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update_one(file_name, pending=False):
    target_dir = PENDING_DIR if pending else DATA_DIR
    path = os.path.join(target_dir, file_name)
    current_header, current_rows = parse_tsv(read_text(path), file_name)
    rows = current_rows
    header = current_header
    added_total = 0
    improved_total = 0
    source_reports = []

    bases = [NPS_BASE_URL]
    for base in bases:
        url = f"{base}/{'pending/' if pending and base == NPS_BASE_URL else ''}{source_name(base, file_name)}"
        try:
            text = fetch_url(url)
            incoming_header, incoming_rows = parse_tsv(text, file_name)
            if not incoming_rows:
                source_reports.append({"url": url, "status": "empty"})
                continue
            if not header and incoming_header:
                header = incoming_header
            rows, added, improved = merge_rows(rows, incoming_rows, file_name)
            added_total += added
            improved_total += improved
            source_reports.append({"url": url, "status": "ok", "rows": len(incoming_rows), "added": added, "improved": improved})
        except Exception as exc:
            source_reports.append({"url": url, "status": "failed", "error": str(exc)})

    if rows:
        write_tsv(path, header, rows, file_name)

    return {
        "rows": len(rows),
        "valid_urls": sum(1 for row in rows if is_url(pkg_url(row))),
        "added": added_total,
        "improved": improved_total,
        "sha256": file_sha256(path) if os.path.exists(path) else "",
        "sources": source_reports,
    }


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(PENDING_DIR, exist_ok=True)
    manifest = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "catalogs": {},
        "pending": {},
    }
    for file_name in CATALOGS:
        manifest["catalogs"][file_name] = update_one(file_name, pending=False)
        manifest["pending"][file_name] = update_one(file_name, pending=True)
        print(f"{file_name}: {manifest['catalogs'][file_name]['rows']} rows, +{manifest['catalogs'][file_name]['added']}")
    with open(MANIFEST_PATH, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
