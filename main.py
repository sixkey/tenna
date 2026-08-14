#!/usr/bin/env python3
"""Controller-driven fullscreen video player for Raspberry Pi.

Pygame handles controller input.  mpv is started once in fullscreen idle mode
and receives commands through its local IPC socket, so changing media never
creates another player window.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pygame


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"


def load_config() -> tuple[Path, Path, dict[int, Path]]:
    with CONFIG_PATH.open(encoding="utf-8") as file:
        config = json.load(file)

    # "button" and "video" are kept for the original one-video config.
    if "buttons" in config:
        raw_buttons = config["buttons"]
        if not isinstance(raw_buttons, dict):
            raise ValueError("'buttons' must be an object of button/video pairs")
    elif isinstance(config.get("button"), int) and isinstance(config.get("video"), str):
        raw_buttons = {str(config["button"]): config["video"]}
    else:
        raise ValueError("config.json needs 'buttons', or both 'button' and 'video'")

    raw_idle = config.get("idle")
    if not isinstance(raw_idle, str):
        raise ValueError("config.json must contain an 'idle' video path")
    idle_video = (APP_DIR / raw_idle).resolve()
    if not idle_video.is_file():
        raise FileNotFoundError(f"Idle video does not exist: {idle_video}")

    raw_blank = config.get("blank")
    if not isinstance(raw_blank, str):
        raise ValueError("config.json must contain a 'blank' image path")
    blank_image = (APP_DIR / raw_blank).resolve()
    if not blank_image.is_file():
        raise FileNotFoundError(f"Blank image does not exist: {blank_image}")

    buttons = {}
    for raw_button, raw_video in raw_buttons.items():
        try:
            button = int(raw_button)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid controller button: {raw_button!r}") from error
        if not isinstance(raw_video, str):
            raise ValueError(f"Video for button {button} must be a string")
        video = (APP_DIR / raw_video).resolve()
        if not video.is_file():
            raise FileNotFoundError(f"Video does not exist: {video}")
        buttons[button] = video

    if not buttons:
        raise ValueError("At least one controller button must be configured")
    return idle_video, blank_image, buttons


class MpvPlayer:
    """A single persistent fullscreen mpv process controlled by JSON IPC."""

    def __init__(self, blank_image: Path) -> None:
        self.socket_path = Path(f"/tmp/tenna-mpv-{os.getpid()}.sock")
        self.blank_image = blank_image
        self.process = None

    def start(self) -> None:
        self.process = subprocess.Popen(
            [
                "mpv",
                # This is a dedicated display appliance. Do not load a
                # desktop MPV configuration or its UI scripts.
                "--no-config",
                # The built-in OSC script renders the idle message even when
                # OSD is disabled, so turn the script itself off.
                "--osc=no",
                "--fs",
                "--idle=yes",
                "--force-window=yes",
                # Prevent MPV's pseudo-GUI idle overlay ("Drop files or URLs
                # to play here") when the app is launched without a terminal.
                "--player-operation-mode=cplayer",
                "--osd-level=0",
                "--image-display-duration=inf",
                # After a triggered video reaches EOF, mpv must return to its
                # idle state so the event loop can reload idle.mp4.
                "--keep-open=no",
                "--really-quiet",
                f"--input-ipc-server={self.socket_path}",
                str(self.blank_image),
            ],
            stdin=subprocess.DEVNULL,
        )

        deadline = time.monotonic() + 5
        while not self.socket_path.exists():
            if self.process.poll() is not None:
                raise RuntimeError("mpv exited before its control socket was ready")
            if time.monotonic() >= deadline:
                raise RuntimeError("Timed out while starting mpv")
            time.sleep(0.05)

    def command(self, command: list) -> None:
        payload = (json.dumps({"command": command}) + "\n").encode("utf-8")
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.connect(str(self.socket_path))
            connection.sendall(payload)
        finally:
            connection.close()

    def is_idle(self) -> bool:
        """Return whether mpv has finished its current non-looping file."""
        payload = (json.dumps({"command": ["get_property", "idle-active"],
                              "request_id": 1}) + "\n").encode("utf-8")
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(2)
            connection.connect(str(self.socket_path))
            connection.sendall(payload)
            received = b""
            while True:
                while b"\n" in received:
                    raw_response, received = received.split(b"\n", 1)
                    response = json.loads(raw_response)
                    # MPV broadcasts events such as "start-file" to IPC
                    # clients. Only the response with our request ID answers
                    # the get_property command.
                    if response.get("request_id") != 1:
                        continue
                    if response.get("error") != "success":
                        raise RuntimeError(f"mpv IPC error: {response.get('error')}")
                    return bool(response.get("data"))

                chunk = connection.recv(4096)
                if not chunk:
                    raise RuntimeError("mpv closed its control socket")
                received += chunk
        finally:
            connection.close()

    def play(self, video: Path, loop: bool = False) -> None:
        # "replace" seamlessly changes the current video in the existing
        # fullscreen mpv window.
        self.command(["set_property", "loop-file", "inf" if loop else "no"])
        self.command(["loadfile", str(video), "replace"])

    def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.socket_path.unlink(missing_ok=True)


def open_first_controller():
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        return None
    controller = pygame.joystick.Joystick(0)
    controller.init()
    print(f"Controller: {controller.get_name()}")
    return controller


def main() -> int:
    if shutil.which("mpv") is None:
        raise RuntimeError("mpv is not installed. Install it with: sudo apt install mpv")

    idle_video, blank_image, buttons = load_config()
    pygame.init()
    # This tiny, minimized Pygame window keeps SDL's controller event queue
    # active while mpv owns the visible fullscreen window.
    pygame.display.set_mode((1, 1))
    pygame.display.iconify()
    controller = open_first_controller()
    if controller is None:
        print("No controller detected. Space plays the first configured video.")

    player = MpvPlayer(blank_image)
    running = True
    try:
        player.start()
        print("Persistent fullscreen player ready.")
        print("Configured buttons:", ", ".join(str(button) for button in sorted(buttons)))
        player.play(idle_video, loop=True)
        playing_idle = True
        next_idle_check = time.monotonic()
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_SPACE:
                        player.play(next(iter(buttons.values())))
                        playing_idle = False
                elif event.type == pygame.JOYBUTTONDOWN and event.button in buttons:
                    # loadfile with "replace" restarts the selected video
                    # from its beginning. A different assigned button swaps
                    # to its video in the same persistent mpv window.
                    player.play(buttons[event.button])
                    playing_idle = False

            # A normal video reaches EOF and makes mpv idle. Return to the
            # looping idle screen without creating or changing windows.
            if not playing_idle and time.monotonic() >= next_idle_check:
                if player.is_idle():
                    player.play(idle_video, loop=True)
                    playing_idle = True
                next_idle_check = time.monotonic() + 0.25
            pygame.time.wait(10)
    finally:
        player.close()
        pygame.quit()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        pygame.quit()
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
