"""Entry point. Run with: python -m snipai"""
import sys
import io

class DummyStream(io.StringIO):
    def write(self, s):
        pass
    def flush(self):
        pass

is_windowed = False
if sys.stdout is None or sys.stderr is None:
    is_windowed = True
else:
    try:
        sys.stdout.write("")
        sys.stdout.flush()
        sys.stderr.write("")
        sys.stderr.flush()
    except Exception:
        is_windowed = True

if is_windowed:
    sys.stdout = DummyStream()
    sys.stderr = DummyStream()

from snipai.app import run

def main():
    sys.exit(run())

if __name__ == "__main__":
    main()
