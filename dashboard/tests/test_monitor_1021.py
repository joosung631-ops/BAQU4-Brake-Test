import unittest
from unittest.mock import patch
from dashboard.monitor_1021 import TrackingDisplay, add_routes
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase


def report():
    return dict(session='fixture', revision='r1', path=dict(frame='map', points=[[0.,0.],[10.,0.]]),
                trail=[dict(seq=1,x=1.,y=0.)], pose=dict(frame='map', fresh=True, position_valid=True))


class TrackingStateTest(unittest.TestCase):
    def test_history_and_connection_age_survive_invalid_pose(self):
        state=TrackingDisplay(); data=report()
        data['pose'].update(x=0.,y=0.,position_valid=False,reason='GNSS_ANTENNA_OBSERVATION_UNAVAILABLE')
        data['last_good_pose']=dict(x=8.,y=2.,frame='map',age_s=3.)
        state.update(data)
        with patch('dashboard.monitor_1021.time.monotonic',return_value=state.received+2):
            snapshot=state.snapshot()
        self.assertFalse(snapshot['active'])
        self.assertEqual(snapshot['server_age_s'],2.)
        self.assertEqual(snapshot['last_good_pose']['x'],8.)
        self.assertEqual(snapshot['pose']['reason'],'GNSS_ANTENNA_OBSERVATION_UNAVAILABLE')

    def test_incremental_history_restart_and_full_path_recovery(self):
        state=TrackingDisplay(); state.update(report())
        first=state.snapshot()
        self.assertTrue(first['reset']); self.assertEqual(first['path']['frame'], 'map')
        second=state.snapshot('fixture',1,'r1')
        self.assertEqual(second['trail'],[]); self.assertNotIn('path',second)
        state.update(report()); self.assertEqual(len(state.trail),1)
        bad=report(); bad['trail'][0]['x']=float('nan')
        with self.assertRaises(ValueError): state.update(bad)
        self.assertEqual(len(state.trail),1)
        restarted=TrackingDisplay(); item=report(); item.pop('path')
        with self.assertRaises(ValueError): restarted.update(item)


class RoutesTest(AioHTTPTestCase):
    async def get_application(self):
        app=web.Application(); add_routes(app); return app

    async def test_read_only_page_and_state(self):
        response=await self.client.post('/api/ros/monitor-1021',json=report())
        self.assertEqual(response.status,204)
        response=await self.client.get('/api/monitor-1021')
        self.assertEqual((await response.json())['path']['points'],[[0.,0.],[10.,0.]])
        page=await self.client.get('/monitor-1021'); self.assertEqual(page.status,200)
        self.assertIn('vehicle_recorder',await page.text())
        command=await self.client.post('/api/monitor-1021',json={'speed':10})
        self.assertEqual(command.status,405)


if __name__ == '__main__': unittest.main()
