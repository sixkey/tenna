# Raspberry Pi video launcher

This is a small Pygame controller application backed by one persistent,
fullscreen `mpv` player. It intentionally does not embed a video surface
inside Pygame: that approach is X11-specific and is unreliable on Raspberry
Pi OS systems using Wayland or KMS/DRM.

## Install on Raspberry Pi OS

```sh
sudo apt update
sudo apt install python3-pygame mpv
```

Connect the Xbox controller before starting the program, place a looping idle
video at `media/idle.mp4`, a black fallback image at `media/blank.png`, and
the triggered video at `media/video.mp4`, then run:

```sh
python3 main.py
```

`idle.mp4` starts immediately and loops until a controller button is pressed.
Button `0` is normally the Xbox **A** button. Each configured button plays its
assigned video; pressing the same button again restarts that video from the
beginning. When a triggered video ends, the player returns to `idle.mp4`.
Configure additional buttons for seamless video switching:

```json
{
  "idle": "media/idle.mp4",
  "blank": "media/blank.png",
  "buttons": {
    "0": "media/video.mp4",
    "1": "media/second-video.mp4"
  }
}
```

Press **Space** to test the first configured video without a controller.
Press **Esc** to exit; mpv's normal **q** key also stops playback.

mpv opens one fullscreen window at startup and remains open. It first displays
the configured blank image and suppresses MPV's default on-screen messages.
Button presses send it commands through a local socket, so playback starts,
restarts, returns to idle, and switches without launching another window.
