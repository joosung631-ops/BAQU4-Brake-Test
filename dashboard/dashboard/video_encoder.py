"""Per-viewer, low-latency H.264/fMP4 encoding. No ROS or network I/O."""
from fractions import Fraction
import io
import time

import av

PROFILES = {5: (600, '25'), 10: (900, '23'), 15: (1200, '22'),
            20: (1400, '21'), 25: (1600, '20.5'), 30: (1800, '20')}


class FragmentSink:
    def __init__(self):
        self.parts = []
        self.position = 0

    def write(self, data):
        self.parts.append(bytes(data)); self.position += len(data)
        return len(data)

    def tell(self):
        return self.position

    def flush(self):
        pass

    def writable(self):
        return True

    def seekable(self):
        return False

    def take(self):
        data = b''.join(self.parts); self.parts.clear()
        return data


class H264Encoder:
    def __init__(self, fps, max_width=640, kbps=None):
        if fps not in PROFILES:
            raise ValueError('FPS must be 5, 10, 15, 20, 25 or 30')
        self.fps, self.max_width = fps, min(640, max_width)
        self.output = None
        self.sink = FragmentSink()
        self.width = self.height = 0
        self.started = None
        self.last_pts = -1
        self.mime = None
        self.frames = 0
        self.kbps = PROFILES[fps][0] if kbps is None else max(100, min(PROFILES[fps][0], int(kbps)))

    def encode(self, jpeg, captured):
        with av.open(io.BytesIO(jpeg), format='mjpeg') as image:
            frame = next(image.decode(video=0))
        scale = min(1, self.max_width / frame.width, 360 / frame.height)
        width = max(2, int(frame.width * scale) // 2 * 2)
        height = max(2, int(frame.height * scale) // 2 * 2)
        if self.output is None:
            self.width, self.height = width, height
            self.output = av.open(self.sink, mode='w', format='mp4', options={
                'movflags': 'empty_moov+default_base_moof+frag_keyframe',
                'frag_duration': '100000', 'flush_packets': '1'})
            self.stream = self.output.add_stream('libx264', rate=self.fps)
            self.stream.width, self.stream.height = width, height
            self.stream.pix_fmt = 'yuv420p'
            self.stream.time_base = Fraction(1, 90000)
            self.stream.codec_context.time_base = Fraction(1, 90000)
            self.stream.codec_context.thread_count = 2
            self.stream.options = {'preset': 'veryfast', 'tune': 'zerolatency',
                'profile': 'baseline', 'level': '3.0', 'crf': PROFILES[self.fps][1],
                'maxrate': str(self.kbps * 1000), 'bufsize': str(self.kbps * 1000),
                'g': str(self.fps * 2), 'keyint_min': str(self.fps * 2),
                'sc_threshold': '0', 'bf': '0'}
            self.started = captured
        if (width, height) != (self.width, self.height):
            raise ValueError('Camera resolution changed; reconnect the stream')
        frame = frame.reformat(width=width, height=height, format='yuv420p')
        frame.pts = max(self.last_pts + 1, round((captured - self.started) * 90000))
        frame.time_base = Fraction(1, 90000)
        self.last_pts = frame.pts
        for packet in self.stream.encode(frame):
            self.output.mux(packet)
        self.frames += 1
        data = self.sink.take()
        if data and self.mime is None:
            offset = data.find(b'avcC')
            if offset < 0 or len(data) < offset + 8:
                raise ValueError('H.264 initialization segment is missing')
            self.mime = 'video/mp4; codecs="avc1.' + data[offset+5:offset+8].hex() + '"'
        return data

    def close(self):
        if self.output is not None:
            self.output.close(); self.output = None
            self.stream = None
        self.sink.take()
