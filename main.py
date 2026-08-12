#!/usr/bin/env python3

import json
import os
import sys

import pygame
import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")

from gi.repository import Gst, GstVideo


CONFIG_FILE = "config.json"


class GStreamerPlayer:
    """
    GStreamer media player.

    A new playbin pipeline is created for each media file.
    Video is rendered into the existing Pygame X11 window.
    Audio is rendered through GStreamer.
    """

    def __init__(self, window_id):
        Gst.init(None)

        self.window_id = window_id
        self.player = None
        self.video_sink = None
        self.audio_sink = None

        self.current_file = None

    def _create_pipeline(self, has_video):
        """
        Create a completely new playbin instance.

        This avoids problems caused by reusing the same playbin
        after switching between video and audio-only media.
        """

        player = Gst.ElementFactory.make(
            "playbin",
            "player"
        )

        if player is None:
            raise RuntimeError(
                "Unable to create GStreamer playbin."
            )

        # ------------------------------------------------------
        # Audio sink
        # ------------------------------------------------------

        audio_sink = Gst.ElementFactory.make(
            "autoaudiosink",
            "audio-sink"
        )

        if audio_sink is None:
            raise RuntimeError(
                "Unable to create GStreamer audio sink."
            )

        player.set_property(
            "audio-sink",
            audio_sink
        )

        # ------------------------------------------------------
        # Video sink
        # ------------------------------------------------------

        if has_video:

            video_sink = Gst.ElementFactory.make(
                "ximagesink",
                "video-sink"
            )

            if video_sink is None:
                raise RuntimeError(
                    "Unable to create ximagesink.\n"
                    "Install gstreamer1.0-x."
                )

            video_sink.set_property(
                "force-aspect-ratio",
                True
            )

            # Attach video to our existing Pygame window.
            GstVideo.VideoOverlay.set_window_handle(
                video_sink,
                self.window_id
            )

            player.set_property(
                "video-sink",
                video_sink
            )

        else:

            # Audio-only media should not try to create or
            # manipulate a video window.
            video_sink = Gst.ElementFactory.make(
                "fakesink",
                "video-sink"
            )

            player.set_property(
                "video-sink",
                video_sink
            )

        self.player = player
        self.video_sink = video_sink
        self.audio_sink = audio_sink

        return player

    def play(self, filename):
        filename = os.path.abspath(filename)

        if not os.path.isfile(filename):
            print(
                f"Media file does not exist: {filename}"
            )
            return

        extension = os.path.splitext(
            filename
        )[1].lower()

        video_extensions = {
            ".mp4",
            ".mkv",
            ".avi",
            ".mov",
            ".webm",
            ".m4v"
        }

        has_video = extension in video_extensions

        # ------------------------------------------------------
        # Completely destroy the previous pipeline.
        # ------------------------------------------------------

        self.stop()

        # ------------------------------------------------------
        # Create a fresh pipeline.
        # ------------------------------------------------------

        try:

            player = self._create_pipeline(
                has_video
            )

            uri = Gst.filename_to_uri(
                filename
            )

            player.set_property(
                "uri",
                uri
            )

            self.current_file = filename

            print(
                f"Playing: {filename}"
            )

            # Start playback.
            result = player.set_state(
                Gst.State.PLAYING
            )

            if result == Gst.StateChangeReturn.FAILURE:

                print(
                    "GStreamer failed to start playback."
                )

                self.stop()

        except Exception as error:

            print(
                f"GStreamer playback error: {error}"
            )

            self.stop()

    def stop(self):
        """
        Completely shut down the current pipeline.
        """

        if self.player is None:
            return

        try:

            self.player.set_state(
                Gst.State.NULL
            )

            # Wait briefly for the state transition to
            # complete before destroying the object.
            self.player.get_state(
                2 * Gst.SECOND
            )

        except Exception as error:

            print(
                f"Error stopping GStreamer: {error}"
            )

        finally:

            self.player = None
            self.video_sink = None
            self.audio_sink = None
            self.current_file = None

    def process_messages(self):
        """
        Process pending GStreamer bus messages.
        """

        if self.player is None:
            return

        bus = self.player.get_bus()

        while True:

            message = bus.timed_pop_filtered(
                0,
                Gst.MessageType.EOS
                | Gst.MessageType.ERROR
                | Gst.MessageType.WARNING
            )

            if message is None:
                break

            if message.type == Gst.MessageType.EOS:

                print(
                    "Playback finished."
                )

                self.stop()

            elif message.type == Gst.MessageType.ERROR:

                error, debug = message.parse_error()

                print(
                    f"GStreamer ERROR: {error}",
                    file=sys.stderr
                )

                if debug:
                    print(
                        f"GStreamer debug: {debug}",
                        file=sys.stderr
                    )

                self.stop()

            elif message.type == Gst.MessageType.WARNING:

                warning, debug = message.parse_warning()

                print(
                    f"GStreamer WARNING: {warning}"
                )

                if debug:
                    print(
                        f"GStreamer debug: {debug}"
                    )

    def close(self):
        self.stop()

def load_config():
    if not os.path.isfile(CONFIG_FILE):
        raise RuntimeError(
            f"Missing {CONFIG_FILE}"
        )

    with open(
        CONFIG_FILE,
        "r",
        encoding="utf-8"
    ) as file:
        return json.load(file)


def initialize_controller():
    pygame.joystick.init()

    count = pygame.joystick.get_count()

    if count == 0:
        raise RuntimeError(
            "No USB game controller detected."
        )

    joystick = pygame.joystick.Joystick(0)
    joystick.init()

    print()
    print("Controller")
    print("----------")
    print(f"Name:    {joystick.get_name()}")
    print(
        f"Buttons: {joystick.get_numbuttons()}"
    )
    print(
        f"Axes:    {joystick.get_numaxes()}"
    )
    print(
        f"Hats:    {joystick.get_numhats()}"
    )
    print()

    return joystick


def get_pygame_window_id():
    """
    Return the native X11 window ID used by Pygame.

    GstVideoOverlay.set_window_handle() expects a native
    window handle. On X11 this is the XID.
    """

    wm_info = pygame.display.get_wm_info()

    window_id = wm_info.get("window")

    if window_id is None:
        raise RuntimeError(
            "Could not obtain the native Pygame window ID.\n"
            "This demo requires an X11 display."
        )

    return int(window_id)


def handle_hat_motion(event, config, player):
    """
    Handle the controller D-pad.

    Pygame normally reports:

        ( 0,  1) = UP
        ( 0, -1) = DOWN
        (-1,  0) = LEFT
        ( 1,  0) = RIGHT
        ( 0,  0) = released
    """

    x, y = event.value

    if x == 0 and y == 1:
        direction = "up"

    elif x == 0 and y == -1:
        direction = "down"

    elif x == -1 and y == 0:
        direction = "left"

    elif x == 1 and y == 0:
        direction = "right"

    else:
        # This is normally the D-pad being released.
        return

    media = (
        config
        .get("directions", {})
        .get(direction)
    )

    if media is None:
        print(
            f"No media configured for D-pad: {direction}"
        )
        return

    print(f"D-pad: {direction}")

    player.play(media)

ANALOG_DEADZONE = 0.5


class DirectionController:
    def __init__(self):
        self.direction = None

    def process_axis(self, event):
        """
        Convert analog axis input into a logical direction.

        Returns:
            "up"
            "down"
            "left"
            "right"
            None
        """

        value = event.value

        # Ignore the small fluctuations around center.
        if abs(value) < ANALOG_DEADZONE:
            return None

        if event.axis == 0:

            if value < 0:
                return "left"

            return "right"

        if event.axis == 1:

            if value < 0:
                return "up"

            return "down"

        return None

    def update(self, event):
        """
        Return a direction only when entering a new direction.

        This prevents a held direction from repeatedly
        restarting the same media.
        """

        direction = self.process_axis(event)

        # Stick returned to center.
        if direction is None:
            self.direction = None
            return None

        # Direction hasn't changed.
        if direction == self.direction:
            return None

        # New direction.
        self.direction = direction

        return direction


def main():

    config = load_config()

    pygame.init()

    # ----------------------------------------------------------
    # Create ONE fullscreen Pygame window.
    # ----------------------------------------------------------

    screen = pygame.display.set_mode(
        (0, 0),
        pygame.FULLSCREEN
    )

    pygame.display.set_caption(
        "Controller Media Player"
    )

    pygame.mouse.set_visible(False)

    # Make the initial screen black.
    screen.fill((0, 0, 0))
    pygame.display.flip()

    # ----------------------------------------------------------
    # Get the native X11 window ID.
    # ----------------------------------------------------------

    window_id = get_pygame_window_id()

    print(
        f"Pygame native window ID: {window_id}"
    )

    # ----------------------------------------------------------
    # Controller
    # ----------------------------------------------------------

    joystick = initialize_controller()

    # ----------------------------------------------------------
    # GStreamer
    # ----------------------------------------------------------

    player = GStreamerPlayer(
        window_id
    )

    clock = pygame.time.Clock()

    print(
        "Controller Media Player started."
    )
    print(
        "Press a controller button to play media."
    )
    print(
        "Press ESC to exit."
    )
    print()

    running = True

    direction_controller = DirectionController()

    try:

        while running:

            # --------------------------------------------------
            # Pygame events
            # --------------------------------------------------

            for event in pygame.event.get():
                print( event )

                if event.type == pygame.QUIT:
                    running = False

                elif event.type == pygame.KEYDOWN:

                    if event.key == pygame.K_ESCAPE:
                        running = False

                elif event.type == pygame.JOYBUTTONDOWN:

                    button = event.button

                    print(
                        f"Button pressed: {button}"
                    )

                    media = (
                        config
                        .get("buttons", {})
                        .get(str(button))
                    )

                    if media is None:

                        print(
                            f"No media assigned to "
                            f"button {button}"
                        )

                        continue

                    player.play(media)

                elif event.type == pygame.JOYHATMOTION:

                    handle_hat_motion(
                        event,
                        config,
                        player
                    )

                elif event.type == pygame.JOYAXISMOTION:

                    direction = direction_controller.update(event)

                    if direction is not None:

                        print(f"Direction: {direction}")

                        media = (
                            config
                            .get("directions", {})
                            .get(direction)
                        )

                        if media is not None:
                            player.play(media)


            # --------------------------------------------------
            # Process GStreamer events.
            # --------------------------------------------------

            player.process_messages()

            # --------------------------------------------------
            # DO NOT call pygame.display.flip() here.
            #
            # GStreamer is rendering the video directly into
            # this same window.
            # --------------------------------------------------

            clock.tick(60)

    except KeyboardInterrupt:

        print(
            "\nStopping..."
        )

    finally:

        player.close()

        pygame.quit()


if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        pygame.quit()

        print(
            f"ERROR: {error}",
            file=sys.stderr
        )

        sys.exit(1)
