"""Optional, bounded latest-only display upload. Never sends actuator inputs."""
import json
import threading
import urllib.request


class PredictionSender:
    def __init__(self, url):
        self.url=url;self.pending=None;self.lock=threading.Lock();self.done=threading.Event()
        self.thread=None
        if url:
            self.thread=threading.Thread(target=self.work,daemon=True);self.thread.start()

    def offer(self, data):
        if self.url:
            with self.lock:self.pending=data

    def work(self):
        while not self.done.wait(.1):
            with self.lock:data,self.pending=self.pending,None
            if data is None:continue
            try:
                request=urllib.request.Request(self.url,data=json.dumps(data,allow_nan=False).encode(),
                    headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(request,timeout=.15) as response:response.read(256)
            except Exception:
                pass  # Viewer loss must not block control or change its decisions.

    def close(self):
        self.done.set()
        if self.thread:self.thread.join(timeout=.4)
