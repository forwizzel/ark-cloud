"""Disposable loopback transport, real sampler and PTY; never invokes host controls."""

import asyncio
import base64
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import psutil
import system_agent

UTC = timezone.utc


@unittest.skipUnless(
    importlib.util.find_spec("websockets"), "Install the host WebSocket dependency"
)
class AgentTransportTests(unittest.TestCase):
    def test_real_agent_transport_terminal_and_job_deduplication(self):
        async def exercise():
            from websockets.asyncio.server import serve

            finished = asyncio.get_running_loop().create_future()

            async def handler(ws):
                async def receive(kind):
                    while True:
                        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=12))
                        if frame["type"] == kind:
                            return frame

                try:
                    snapshot = await receive("snapshot")
                    self.assertEqual(snapshot["snapshot"]["scope"], "host")
                    job = {
                        "type": "job",
                        "id": "disposable-job",
                        "boot_id": snapshot["snapshot"]["boot_id"],
                        "deadline": (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
                        "payload": {
                            "action": "service",
                            "unit": "fixture.service",
                            "scope": "user",
                            "operation": "restart",
                        },
                    }
                    await ws.send(json.dumps(job))
                    self.assertEqual((await receive("job_result"))["state"], "succeeded")
                    await ws.send(json.dumps(job))
                    self.assertEqual((await receive("job_result"))["state"], "succeeded")
                    await ws.send(
                        json.dumps({"type": "terminal_start", "id": "disposable-terminal"})
                    )
                    await receive("terminal_output")
                    await ws.send(
                        json.dumps(
                            {
                                "type": "terminal_input",
                                "id": "disposable-terminal",
                                "data": base64.b64encode(
                                    b"printf '\\101\\122\\113_AGENT_OK\\n'\n"
                                ).decode(),
                            }
                        )
                    )
                    output = b""
                    while b"ARK_AGENT_OK\r\n" not in output:
                        frame = await receive("terminal_output")
                        output += base64.b64decode(frame["data"])
                    await ws.send(json.dumps({"type": "terminal_end", "id": "disposable-terminal"}))
                    finished.set_result(True)
                except BaseException as error:
                    if not finished.done():
                        finished.set_exception(error)
                    raise

            with (
                tempfile.TemporaryDirectory() as directory,
                patch.object(system_agent, "STATE", Path(directory)),
                patch.object(
                    system_agent, "execute", return_value="Fixture operation completed."
                ) as execute,
            ):
                async with serve(handler, "127.0.0.1", 0) as server:
                    port = server.sockets[0].getsockname()[1]
                    config = {
                        "url": f"ws://127.0.0.1:{port}/api/system-agent/connect",
                        "uid": os.getuid(),
                        "token": "disposable-test-token",
                        "directory": directory,
                        "policy": {
                            "terminal": True,
                            "power": False,
                            "processes": False,
                            "shell": "/bin/bash",
                            "account": "fixture",
                            "services": [],
                        },
                    }
                    agent = asyncio.create_task(system_agent.connection(config))
                    try:
                        await asyncio.wait_for(finished, timeout=20)
                        await asyncio.wait_for(agent, timeout=5)
                        self.assertEqual(execute.call_count, 1)
                    finally:
                        agent.cancel()
                        await asyncio.gather(agent, return_exceptions=True)
            self.assertEqual(psutil.Process().children(), [])

        asyncio.run(exercise())
