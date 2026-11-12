"""Export only 2026-09-20 GPS tracks. Run on host (Python + PyYAML + zstd).

Compressed SQLite files are expanded one at a time in a temporary directory.
Original bags are always read-only. Output uses a common WGS84 ECEF/ENU origin.
"""
import argparse
import json
import math
from pathlib import Path
import sqlite3
import struct
import subprocess
import tempfile
import yaml


class CDR:
    def __init__(self, blob):
        if blob[:2] not in (b'\x00\x00', b'\x00\x01'):
            raise ValueError('Unsupported CDR encoding')
        self.data = memoryview(blob)[4:]
        self.pos = 0
        self.order = '<' if blob[1] == 1 else '>'

    def read(self, fmt, alignment):
        self.pos = (self.pos + alignment - 1) // alignment * alignment
        result = struct.unpack_from(self.order + fmt, self.data, self.pos)
        self.pos += struct.calcsize(self.order + fmt)
        return result

    def string(self):
        size, = self.read('I', 4)
        self.pos += size


def decode_fix(blob):
    c = CDR(blob)
    sec, nsec = c.read('iI', 4)
    c.string()
    status, = c.read('b', 1)
    c.read('H', 2)
    lat, lon, alt = c.read('ddd', 8)
    return sec + nsec / 1e9, status, lat, lon, alt


def ecef(lat, lon, alt):
    lat, lon = math.radians(lat), math.radians(lon)
    e2 = 6.6943799901413165e-3
    n = 6378137 / math.sqrt(1 - e2 * math.sin(lat)**2)
    return ((n + alt)*math.cos(lat)*math.cos(lon),
            (n + alt)*math.cos(lat)*math.sin(lon),
            (n*(1-e2) + alt)*math.sin(lat))


def enu(lat, lon, origin):
    # Plan-view tracks use the common ellipsoid height (not a surveyed 3D map).
    a, b, h = origin
    x, y, z = [v-u for v, u in zip(ecef(lat, lon, h), ecef(a, b, h))]
    a, b = math.radians(a), math.radians(b)
    return (-math.sin(b)*x + math.cos(b)*y,
            -math.sin(a)*math.cos(b)*x - math.sin(a)*math.sin(b)*y + math.cos(a)*z)


def read_db(path):
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        return list(db.execute("SELECT topics.name, messages.timestamp, messages.data FROM messages JOIN topics ON topics.id=messages.topic_id WHERE topics.name IN ('/gnss/fix','/gnss/status') ORDER BY messages.timestamp"))


def export(root):
    bags = []
    origin = None
    for folder in sorted(root.glob('2026-09-20_*'), key=lambda p: int(p.name.rsplit('_', 1)[1])):
        meta = yaml.safe_load((folder/'metadata.yaml').read_text())['rosbag2_bagfile_information']
        bag = {'id': folder.name, 'duration': round(meta['duration']['nanoseconds']/1e9, 2), 'points': [], 'invalid': 0}
        count = sum(t['message_count'] for t in meta['topics_with_message_count'] if t['topic_metadata']['name'] == '/gnss/fix')
        rows = []
        if count:
            for relative in meta['relative_file_paths']:
                source = folder / relative
                plain = source.with_suffix('') if source.suffix == '.zstd' else source
                if plain.exists():
                    rows.extend(read_db(plain))
                else:
                    with tempfile.TemporaryDirectory(prefix='dashboard-gps-') as tmp:
                        unpacked = Path(tmp)/'bag.db3'
                        subprocess.run(['zstd', '-q', '-d', str(source), '-o', str(unpacked)], check=True)
                        rows.extend(read_db(unpacked))
        rows.sort(key=lambda row: row[1])
        qualities = [(t, int(blob[4])) for name, t, blob in rows if name == '/gnss/status']
        import bisect
        quality_times = [t for t, _ in qualities]
        for name, recorded, blob in rows:
            if name != '/gnss/fix':
                continue
            stamp, status, lat, lon, alt = decode_fix(blob)
            if status < 0 or not all(map(math.isfinite, (lat, lon))) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                bag['invalid'] += 1
                continue
            if origin is None:
                origin = [lat, lon, alt if math.isfinite(alt) else 0]
            idx = bisect.bisect_left(quality_times, recorded)
            candidates = [i for i in (idx-1, idx) if 0 <= i < len(qualities)]
            nearest = min(candidates, key=lambda i: abs(quality_times[i]-recorded)) if candidates else None
            quality = qualities[nearest][1] if nearest is not None and abs(quality_times[nearest]-recorded) <= 200_000_000 else None
            east, north = enu(lat, lon, origin)
            bag['points'].append({'t': recorded/1e9, 'stamp': stamp, 'lat': lat, 'lon': lon, 'e': round(east, 3), 'n': round(north, 3), 'quality': quality})
        bag['fixed'] = sum(p['quality'] == 4 for p in bag['points'])
        bags.append(bag)
        print(folder.name, len(bag['points']), 'valid fixes', flush=True)
    return {'date': '2026-09-20', 'origin': origin, 'bags': bags}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bags', type=Path, default=Path('main/bags/2026-09-20'))
    parser.add_argument('--output', type=Path, default=Path('dashboard/data/gps-2026-09-20.json'))
    args = parser.parse_args()
    if args.bags.name != '2026-09-20':
        parser.error('Only 2026-09-20 bags are supported')
    data = export(args.bags)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
    temporary.replace(args.output)
