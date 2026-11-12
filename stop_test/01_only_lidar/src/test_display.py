import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from display import PredictionSender


class Tests(unittest.TestCase):
    def test_optional_latest_only_upload_and_http_failure_do_not_block_offer(self):
        disabled=PredictionSender('');disabled.offer({'seq':1});disabled.close();self.assertIsNone(disabled.thread)
        received=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(503);self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        sender=PredictionSender('http://127.0.0.1:'+str(server.server_port)+'/preview')
        try:
            started=time.monotonic()
            for i in range(100):sender.offer({'seq':i})
            self.assertLess(time.monotonic()-started,.05)
            deadline=time.monotonic()+2
            while not received and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(received[-1]['seq'],99)
        finally:sender.close();server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
