"""Memory-only display endpoint for monitor_1021. No ROS or disk recording."""
from collections import deque
import math
from pathlib import Path
import time
from aiohttp import web


def finite_numbers(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('nonfinite display value')
    if isinstance(value, dict):
        for item in value.values(): finite_numbers(item)
    elif isinstance(value, list):
        for item in value: finite_numbers(item)


class TrackingDisplay:
    def __init__(self):
        self.session, self.revision, self.path = '', '', None
        self.values, self.last_sequence = {}, 0
        self.trail = deque(maxlen=10000)
        self.received = None

    def update(self, data):
        if not isinstance(data, dict): raise ValueError('invalid report')
        finite_numbers(data)
        session, revision = data.get('session'), data.get('revision')
        if not isinstance(session, str) or not 1 <= len(session) <= 64: raise ValueError('invalid session')
        if not isinstance(revision, str) or len(revision) > 64: raise ValueError('invalid revision')
        rows = data.get('trail', [])
        if not isinstance(rows, list) or len(rows) > 200: raise ValueError('invalid trail')
        for row in rows:
            if not isinstance(row, dict) or type(row.get('seq')) is not int or row['seq'] < 1:
                raise ValueError('invalid trail sequence')
            if any(type(row.get(key)) not in (int, float) for key in ('x', 'y')): raise ValueError('invalid XY')
        path = data.get('path')
        if any(key in data and not isinstance(data[key], dict) for key in ('pose', 'diagnostic', 'motion', 'command', 'control')):
            raise ValueError('invalid display fields')
        for key in ('last_good_pose', 'reference'):
            if data.get(key) is not None and not isinstance(data[key], dict):
                raise ValueError('invalid display history')
        if path is not None:
            if not isinstance(path, dict) or not isinstance(path.get('frame'), str): raise ValueError('invalid frame')
            points = path.get('points')
            if not isinstance(points, list) or len(points) > 20000 or any(
                not isinstance(p, (list, tuple)) or len(p) != 2 or any(type(v) not in (int, float) for v in p) for p in points):
                raise ValueError('invalid path')
        if revision and path is None and (session != self.session or revision != self.revision):
            raise ValueError('full path required')
        if session != self.session:
            self.trail.clear(); self.last_sequence = 0; self.path = None
        old_frame = self.values.get('pose', {}).get('frame')
        new_frame = data.get('pose', {}).get('frame')
        if old_frame and old_frame != new_frame:
            self.trail.clear()
        self.session, self.revision = session, revision
        if path is not None: self.path = path
        for row in rows:
            if row['seq'] > self.last_sequence:
                self.trail.append(dict(seq=row['seq'], x=row['x'], y=row['y']))
                self.last_sequence = row['seq']
        self.values = {key: data[key] for key in ('pose', 'diagnostic', 'motion', 'command', 'control',
                      'last_good_pose', 'reference') if isinstance(data.get(key), dict)}
        self.received = time.monotonic()

    def snapshot(self, session='', after=0, revision=''):
        reset = session != self.session or (self.trail and after < self.trail[0]['seq']-1)
        age = max(0., time.monotonic()-self.received) if self.received is not None else None
        result = dict(session=self.session, revision=self.revision, sequence=self.last_sequence,
                      active=age is not None and age < 1., server_age_s=age,
                      reset=bool(reset), trail=[p for p in self.trail if reset or p['seq'] > after], **self.values)
        if session != self.session or revision != self.revision: result['path'] = self.path
        return result


def add_routes(app):
    state = TrackingDisplay()

    async def receive(request):
        try: state.update(await request.json())
        except (ValueError, TypeError, AttributeError): raise web.HTTPBadRequest(text='Invalid tracking display report')
        return web.Response(status=204)

    async def snapshot(request):
        try: after = max(0, int(request.query.get('after', '0')))
        except ValueError: raise web.HTTPBadRequest(text='Invalid sequence')
        return web.json_response(state.snapshot(request.query.get('session', ''), after, request.query.get('revision', '')),
                                 headers={'Cache-Control': 'no-store'})

    async def page(request):
        return web.FileResponse(Path(__file__).with_name('monitor-1021.html'), headers={'Cache-Control': 'no-cache'})

    async def script(request):
        return web.FileResponse(Path(__file__).with_name('monitor-1021.js'), headers={'Cache-Control': 'no-cache'})

    app.router.add_post('/api/ros/monitor-1021', receive)
    app.router.add_get('/api/monitor-1021', snapshot)
    app.router.add_get('/monitor-1021', page)
    app.router.add_get('/monitor-1021.js', script)
    return state
