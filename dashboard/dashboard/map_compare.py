"""Read ordered GPS vertices for overlaying maps without spline smoothing."""
import asyncio
import json
from pathlib import Path
from aiohttp import web
from .gps_project import directory, load as load_project
from .gps_path import path_source
from .map_position import map_points


def comparison_points(document):
    if document.get('format') == 'gps-map-project':
        stages = document.get('stages', {})
        if not stages.get('7', {}).get('ordered_points'):
            raise ValueError('7단계 순서 GPS가 있는 프로젝트 또는 최종 MAP을 선택하세요.')
        # The saved stage-8 spline is a rear-axle path. Compare the editable
        # GPS antenna vertices used by the final piecewise-linear export.
        source = path_source(document)
        points = []
        previous = None
        for p in source['points']:
            segment = p['segment_index']
            points.append({**p, 'break_before': previous is not None and previous != segment})
            previous = segment
        result = map_points({'points': points})
        result['source'] = 'GPS 웨이포인트 (8단계 편집 반영)' if stages.get('8', {}).get('source_digest') == source['source_digest'] else '7단계 순서 GPS'
    else:
        if not isinstance(document.get('points'), list):
            raise ValueError('GPS 포인트가 있는 최종 MAP을 선택하세요.')
        result = map_points(document)
        result['source'] = '최종 MAP 저장 포인트' if document.get('format') == 'gps-final-map' else '저장 GPS 포인트'
    return {**result, 'interpolation': 'piecewise_linear', 'reference_point': 'gps_antenna'}


def add_routes(app):
    def allowed(path):
        return path.suffix == '.json' and not path.is_symlink() and path.is_file()

    async def listing(request):
        names = await asyncio.to_thread(lambda: sorted(p.name for p in directory().glob('*.json') if allowed(p)))
        return web.json_response({'maps': names}, headers={'Cache-Control': 'no-store'})

    async def load(request):
        name = request.match_info['name']
        if Path(name).name != name or '/' in name or '\\' in name or name.startswith('.'):
            raise web.HTTPNotFound()

        def read():
            path = directory() / name
            if not allowed(path):
                raise FileNotFoundError(name)
            document = json.loads(path.read_text())
            if not isinstance(document, dict):
                raise ValueError('지도 JSON 객체가 필요합니다.')
            if document.get('format') == 'gps-map-project' and document.get('version', 1) < 3:
                document = load_project(name)
            return {'filename': name, **comparison_points(document)}

        try:
            data = await asyncio.to_thread(read)
        except FileNotFoundError:
            raise web.HTTPNotFound(text='지도 파일을 찾을 수 없습니다.')
        except PermissionError:
            raise web.HTTPForbidden(text='지도 파일을 읽을 수 없습니다.')
        except (ValueError, TypeError, KeyError, AttributeError, web.HTTPConflict) as error:
            raise web.HTTPBadRequest(text='지도를 불러올 수 없습니다: ' + getattr(error, 'text', str(error)))
        return web.json_response(data, headers={'Cache-Control': 'no-store'})

    app.router.add_get('/api/map-compare/maps', listing)
    app.router.add_get('/api/map-compare/maps/{name}', load)
