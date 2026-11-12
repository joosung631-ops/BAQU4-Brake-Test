"""Run the header counter and unprivileged webserver in the existing container."""
import os
import pwd
import signal
import subprocess
import sys
import time


def web_user():
    user = pwd.getpwnam('dashboard')
    os.setgroups([])
    os.setgid(user.pw_gid)
    os.setuid(user.pw_uid)


def signal_child(child, signum):
    try:
        child.send_signal(signum)
    except PermissionError:
        # The web child runs as UID 10001; the parent intentionally has no CAP_KILL.
        subprocess.run([sys.executable, '-c',
            'import os,signal,sys; os.kill(int(sys.argv[1]),int(sys.argv[2]))',
            str(child.pid), str(signum)], preexec_fn=web_user, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except ProcessLookupError:
        pass


def main():
    children = []
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        children.append(subprocess.Popen([sys.executable, '-m', 'dashboard.internet_meter']))
        children.append(subprocess.Popen([sys.executable, '-m', 'dashboard'], preexec_fn=web_user))
        while not stopping and all(child.poll() is None for child in children):
            time.sleep(0.25)
        return 0 if stopping else 1
    finally:
        for child in children:
            if child.poll() is None:
                signal_child(child, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                signal_child(child, signal.SIGKILL)
                child.wait()


if __name__ == '__main__':
    sys.exit(main())
