import time
from pathlib import Path
from urllib.request import urlopen

age = time.monotonic() - float(Path("/tmp/controller-heartbeat").read_text())
assert 0 <= age < 90
if Path("/tmp/gateway-ready").exists():
    with urlopen("http://127.0.0.1:8080/_ark_controller_health", timeout=2) as response:
        assert response.status == 204
