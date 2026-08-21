"""RealTunnel — SSH 터널(k3s API 6443) 자동 관리.

시스템 ssh를 subprocess로 소유(-N -L) — 별도 SSH 라이브러리 없음.
감시 루프가 프로세스 생존·포트 개통을 확인하고, 죽으면 백오프 재접속.
포트가 이미 열려 있으면(수동/외부 터널) 새로 띄우지 않고 그대로 사용.
"""
from __future__ import annotations

import asyncio
import os

_BACKOFFS = (2, 5, 10, 30, 60)  # 재접속 간격(초) — 마지막 값으로 수렴
_HEALTH_INTERVAL = 10           # 연결 상태 재확인 주기(초)


def build_ssh_command(s) -> list[str]:
    """settings → ssh 실행 인자. 순수함수 (테스트: test_real_helpers)."""
    cmd = [
        "ssh", "-N",
        "-L", f"{s.local_tunnel_port}:{s.local_tunnel_target}",
        "-p", str(s.local_ssh_port),
        "-o", "ExitOnForwardFailure=yes",   # 포워딩 실패 시 즉시 종료 → 감시 루프가 감지
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=3",
        "-o", "BatchMode=yes",              # 패스워드 프롬프트로 블록되지 않게
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
    ]
    if s.local_ssh_key_path:
        cmd += ["-i", os.path.expanduser(s.local_ssh_key_path)]
    dest = f"{s.local_ssh_user}@{s.local_ssh_host}" if s.local_ssh_user else s.local_ssh_host
    cmd.append(dest)
    return cmd


async def _port_open(port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=1.5)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    await writer.wait_closed()
    return True


class RealTunnel:
    def __init__(self, settings):
        self.s = settings
        self._proc: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task | None = None
        self._state = "connecting"
        self._detail = ""

    def status(self) -> dict:
        return {"state": self._state, "detail": self._detail}

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._keeper())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._terminate()
        self._state = "disabled"

    async def _keeper(self) -> None:
        attempt = 0
        try:
            while True:
                if await _port_open(self.s.local_tunnel_port):
                    self._state = "connected"
                    self._detail = ("앱 관리 터널" if self._proc is not None
                                    else "외부 터널 사용 중 (포트 이미 개방)")
                    attempt = 0
                    # 우리 프로세스가 죽었는데 포트만 남은 경우는 다음 확인에서 걸러짐
                    if self._proc is not None and self._proc.returncode is not None:
                        self._proc = None
                    await asyncio.sleep(_HEALTH_INTERVAL)
                    continue

                # 포트 닫힘 — 우리가 띄운 프로세스가 있으면 정리 후 재시도
                exited = await self._terminate()
                self._state = "retrying" if attempt else "connecting"
                if exited:
                    self._detail = f"ssh 종료({exited[0]}): {exited[1]}" if exited[1] \
                        else f"ssh 종료(코드 {exited[0]})"
                await self._spawn()
                # 개통 대기 (최대 ~8초) — 실패면 백오프 후 루프 재진입
                for _ in range(8):
                    await asyncio.sleep(1)
                    if await _port_open(self.s.local_tunnel_port):
                        break
                else:
                    await asyncio.sleep(_BACKOFFS[min(attempt, len(_BACKOFFS) - 1)])
                    attempt += 1
        finally:
            await self._terminate()

    async def _spawn(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            *build_ssh_command(self.s),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

    async def _terminate(self) -> tuple[int, str] | None:
        """ssh 프로세스 종료·수거. 죽어 있었으면 (코드, stderr 꼬리) 반환."""
        proc, self._proc = self._proc, None
        if proc is None:
            return None
        if proc.returncode is None:
            proc.terminate()
        try:
            stderr = b""
            if proc.stderr is not None:
                stderr = await asyncio.wait_for(proc.stderr.read(), timeout=3)
            await asyncio.wait_for(proc.wait(), timeout=3)
        except asyncio.TimeoutError:
            proc.kill()
            return (proc.returncode or -9, "")
        tail = stderr.decode("utf-8", errors="replace").strip().splitlines()
        return (proc.returncode, tail[-1][:200] if tail else "")
