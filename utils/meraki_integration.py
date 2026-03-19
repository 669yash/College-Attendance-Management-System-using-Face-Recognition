import os
import io
import time
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import requests
import csv
from config import MERAKI_API_KEY, MERAKI_NETWORK_ID, CAMERA_CLASSROOM_SERIALS, CAMERA_OUTDOOR_SERIALS, CAMERAS_CSV_PATH, MERAKI_SNAPSHOT_INTERVAL_SECONDS, UNREGISTERED_FOLDER

def _client():
    try:
        import meraki
    except Exception:
        return None
    if not MERAKI_API_KEY:
        return None
    return meraki.DashboardAPI(api_key=MERAKI_API_KEY, suppress_logging=True)

_snapshot_cache: Dict[str, Tuple[float, str]] = {}
_snapshot_folder = UNREGISTERED_FOLDER.parent / 'snapshots'
_snapshot_folder.mkdir(parents=True, exist_ok=True)
_fail_backoff_until: Dict[str, float] = {}  # serial -> unix_ts until which we skip fetch attempts
_global_fail_until: float = 0.0  # skip all fetches until this time if client missing

def _client_available() -> bool:
    return _client() is not None

def generate_snapshot_url(serial: str, timestamp: Optional[str] = None) -> Optional[str]:
    c = _client()
    if c is None:
        return None
    try:
        r = c.camera.generateDeviceCameraSnapshot(serial, timestamp=timestamp)
        return r.get('url')
    except Exception:
        return None

def download_snapshot(url: str) -> Optional[bytes]:
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code == 200:
            return resp.content
    except Exception:
        return None
    return None

def save_snapshot_bytes(data: bytes, folder: Path, filename: str) -> Optional[str]:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        fp = folder / filename
        with open(str(fp), 'wb') as f:
            f.write(data)
        return str(fp)
    except Exception:
        return None

def fetch_snapshot_to_folder(serial: str, folder: Path, prefix: str = "snapshot") -> Optional[str]:
    url = generate_snapshot_url(serial)
    if not url:
        return None
    data = download_snapshot(url)
    if not data:
        return None
    ts = int(time.time())
    name = f"{prefix}_{ts}.jpg"
    return save_snapshot_bytes(data, folder, name)

def get_or_fetch_cached_snapshot(serial: str) -> Optional[str]:
    now = time.time()
    if serial in _snapshot_cache:
        ts, path = _snapshot_cache[serial]
        if now - ts < MERAKI_SNAPSHOT_INTERVAL_SECONDS and Path(path).exists():
            return path
    # If Meraki client is not available, return cached file only (no fresh fetch)
    if not _client_available():
        entry = _snapshot_cache.get(serial)
        if entry and Path(entry[1]).exists():
            return entry[1]
        return None
    # Backoff after failures for this serial
    if _fail_backoff_until.get(serial, 0) > now:
        entry = _snapshot_cache.get(serial)
        return entry[1] if entry and Path(entry[1]).exists() else None
    p = fetch_snapshot_to_folder(serial, _snapshot_folder, prefix=serial)
    if p:
        _snapshot_cache[serial] = (now, p)
        return p
    # Record failure backoff (60s)
    _fail_backoff_until[serial] = now + 60
    return None

def _load_csv_rows() -> List[Dict]:
    rows: List[Dict] = []
    if not CAMERAS_CSV_PATH:
        return rows
    try:
        with open(CAMERAS_CSV_PATH, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append({k.strip(): (v or '').strip() for k, v in r.items()})
    except Exception:
        return []
    return rows

def get_camera_catalog() -> List[Dict]:
    # Try Meraki first; fall back to CSV-only if Meraki is unavailable
    devices: List[Dict] = []
    try:
        c = _client()
        if c is not None:
            devices = c.networks.getNetworkDevices(MERAKI_NETWORK_ID)
    except Exception:
        devices = []
    meraki_cameras = [d for d in devices if d.get('model') and str(d['model']).startswith('MV')]
    meraki_by_serial = {d.get('serial'): d for d in meraki_cameras if d.get('serial')}

    csv_rows = _load_csv_rows()
    def _get_serial_key(r: Dict) -> Optional[str]:
        return (
            r.get('Serial number') or r.get('Serial Number') or r.get('Serial') or
            r.get('serial') or r.get('SERIAL') or r.get('SERIAL NUMBER') or
            r.get('Serial No') or r.get('Serial_No') or r.get('SERIAL_NO')
        )
    csv_by_serial: Dict[str, Dict] = {}
    for r in csv_rows:
        sk = _get_serial_key(r)
        if sk:
            csv_by_serial[sk] = r

    # Union of serials from Meraki and CSV
    all_serials = set(meraki_by_serial.keys()) | set(csv_by_serial.keys())
    catalog: List[Dict] = []
    for serial in all_serials:
        cam = meraki_by_serial.get(serial, {})
        csv_r = csv_by_serial.get(serial)
        name = (csv_r.get('Name') if csv_r else None) or cam.get('name') or serial
        tags = (csv_r.get('Tags') if csv_r else None) or (csv_r.get('Tag') if csv_r else None) or ''
        # Prefer explicit location fields; else derive from tags (first token)
        location = (
            (csv_r.get('Location') if csv_r else None) or
            (csv_r.get('Site') if csv_r else None) or
            (csv_r.get('Camera Location') if csv_r else None) or
            (csv_r.get('ROOM') if csv_r else None)
        )
        if not location and tags:
            # Split tags by common delimiters and take the first non-empty token as a proxy for location
            for delim in [',', ';', '|', '/']:
                if delim in tags:
                    location = tags.split(delim)[0].strip()
                    break
            if not location:
                location = tags.strip()
        model = cam.get('model') or ''
        indoor = False
        outdoor = False
        if serial in CAMERA_CLASSROOM_SERIALS:
            indoor = True
        if serial in CAMERA_OUTDOOR_SERIALS:
            outdoor = True
        t = tags.lower()
        if 'indoor' in t or 'class' in t or 'classroom' in t or 'room' in t:
            indoor = True
        if 'outdoor' in t or 'gate' in t or 'parking' in t:
            outdoor = True
        kind = 'indoor' if indoor and not outdoor else ('outdoor' if outdoor and not indoor else ('indoor' if indoor else ('outdoor' if outdoor else 'unknown')))
        catalog.append({
            'serial': serial,
            'name': name,
            'model': model,
            'tags': tags,
            'location': location or '',
            'kind': kind
        })
    return catalog

def get_categorized_cameras():
    try:
        catalog = get_camera_catalog()
        classroom_cameras = [c for c in catalog if c.get('kind') == 'indoor']
        outdoor_cameras = [c for c in catalog if c.get('kind') == 'outdoor']
        if not classroom_cameras and not outdoor_cameras and catalog:
            classroom_cameras = catalog
        return {'classroom': classroom_cameras, 'outdoor': outdoor_cameras}
    except Exception:
        return {'classroom': [], 'outdoor': []}
