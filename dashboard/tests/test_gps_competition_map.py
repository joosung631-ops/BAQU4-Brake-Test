"""Fixed competition maps require confirmation and preserve the exported bytes."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from dashboard.gps_project import add_routes


class CompetitionMapTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.maps = self.root / 'maps'
        self.maps.mkdir()
        self.env = patch.dict(os.environ, {'DASHBOARD_GPS_REVIEW_DIR': str(self.root)})
        self.env.start()
        self.source = self.maps / 'MAP_2026-10-20_120000_test.json'
        self.content = b'{"format":"gps-final-map", "points": [1, 2]}\n'
        self.source.write_bytes(self.content)
        app = web.Application()
        add_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.env.stop()
        self.tmp.cleanup()

    async def status(self, category):
        response = await self.client.get('/api/gps/projects/competition-map', params={'category': category})
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def save(self, category, expected=None, status=200, **extra):
        response = await self.client.post('/api/gps/projects/competition-map',
            json={'category': category, 'source_filename': self.source.name, 'expected_digest': expected, **extra},
            headers={'X-Dashboard-Control': '1'})
        self.assertEqual(response.status, status, await response.text())
        return await response.json() if status == 200 else None

    async def test_each_category_has_one_exact_copy_and_other_maps_survive(self):
        for category in ('preliminary', 'final'):
            preview = await self.status(category)
            self.assertFalse(preview['exists'])
            result = await self.save(category)
            self.assertEqual((self.maps / result['filename']).read_bytes(), self.content)
            self.assertFalse(result['overwritten'])
        self.source.write_bytes(self.content.replace(b'[1, 2]', b'[3, 4]'))
        previous = await self.status('preliminary')
        self.assertTrue(previous['exists'])
        result = await self.save('preliminary', previous['digest'])
        self.assertTrue(result['overwritten'])
        self.assertEqual((self.maps / 'MAP_preliminary.json').read_bytes(), self.source.read_bytes())
        self.assertEqual((self.maps / 'MAP_final.json').read_bytes(), self.content)
        self.assertEqual(len(list(self.maps.glob('MAP_preliminary*.json'))), 1)
        self.assertEqual(len(list(self.maps.glob('*.json'))), 3)

    async def test_existing_and_concurrently_changed_files_need_new_confirmation(self):
        target = self.maps / 'MAP_final.json'
        target.write_bytes(b'old map')
        preview = await self.status('final')
        await self.save('final', status=409)
        self.assertEqual(target.read_bytes(), b'old map')
        target.write_bytes(b'newer map')
        await self.save('final', preview['digest'], status=409)
        self.assertEqual(target.read_bytes(), b'newer map')
        preview = await self.status('final')
        self.assertEqual(preview['digest'], hashlib.sha256(b'newer map').hexdigest())
        await self.save('final', preview['digest'])
        self.assertEqual(target.read_bytes(), self.content)

    async def test_write_failure_keeps_existing_map_and_removes_temporary_file(self):
        target = self.maps / 'MAP_final.json'
        target.write_bytes(b'keep old map')
        preview = await self.status('final')
        before = set(self.maps.iterdir())
        with patch('dashboard.gps_project.Path.replace', side_effect=web.HTTPInsufficientStorage()):
            await self.save('final', preview['digest'], status=507)
        self.assertEqual(target.read_bytes(), b'keep old map')
        self.assertEqual(set(self.maps.iterdir()), before)

    async def test_invalid_category_source_and_missing_confirmation_do_not_write(self):
        await self.save('../outside', status=400)
        await self.save('final', source_filename='../outside.json', status=400)
        self.source.write_text('{"format":"gps-map-project"}')
        await self.save('final', status=400)
        response = await self.client.post('/api/gps/projects/competition-map',
            json={'category': 'final', 'source_filename': self.source.name},
            headers={'X-Dashboard-Control': '1'})
        self.assertEqual(response.status, 400)
        self.assertFalse((self.maps / 'MAP_final.json').exists())
