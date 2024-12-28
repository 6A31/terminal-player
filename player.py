#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import time
import curses
import cv2
from PIL import Image
import youtube_dl
import vlc
from pytube import extract
from youtube_transcript_api import YouTubeTranscriptApi

################################################################################
# ---------------------------- GLOBAL CONFIG ---------------------------------- #
################################################################################

ydl_opts = {
    'format': 'bestvideo[ext=mp4]+bestaudio[ext=mp4]/mp4',
    'outtmpl': 'YouTubeTemporary/video.%(ext)s',
}

# Flags
YT = False               # True if using YouTube
UseCachedFrames = False  # True if -c is specified
Subtitles = False        # True if -sub is specified
SubtitlesLang = None
SubtitlesUseLang = False
DisableDynamicSkip = False  # If True, don't skip frames to catch up
DebugFPS = False           # If True, show live FPS in top-right corner
PreviousCaptionsArrayIndex = 0

chars = ["B", "S", "#", "&", "@", "$", "%", "*", "!", ".", " "]

Video_FPS = None
Video_Frames = None
stdscr = None

User_FPS = None  # If provided by -f

# We'll define a color pair index for the green FPS text
GREEN_PAIR_IDX = 1  # arbitrary "pair number" for curses

################################################################################
# ----------------------------- ARG PARSING ----------------------------------- #
################################################################################

def print_help():
    help_text = """
Usage: ascii_player.py [options] <local_file> or -y <YouTubeLink>

Options:
  -y <link>    Play a YouTube video (downloads it first).
  -c           Use cached frames (skip extraction & resizing; 'resized/' must exist).
  -sub [lang]  Enable YouTube subtitles; optional language code.
  -f <fps>     Set a custom ASCII framerate (displays fewer frames per second).
               Audio still plays at normal speed (frames are skipped).
  -noskip      Disable dynamic skipping. If the program falls behind schedule,
               it won't skip frames to catch up (video may get out of sync).
  -debug       Show live FPS (number of frames drawn per second) in the top-right corner (in green).
  -h, -help    Show this help message and exit.

Examples:
  # Local file, normal run
  python ascii_player.py movie.mp4

  # Local file, skip extraction/resizing (cached frames):
  python ascii_player.py movie.mp4 -c

  # YouTube, with default subtitles:
  python ascii_player.py -y https://www.youtube.com/watch?v=XYZ -sub

  # YouTube, with English subtitles, 10 FPS display:
  python ascii_player.py -y https://www.youtube.com/watch?v=XYZ -sub en -f 10

  # Local file, 15 FPS display, disable dynamic skipping, debug on:
  python ascii_player.py movie.mp4 -f 15 -noskip -debug
"""
    print(help_text)


def parse_args(args):
    global YT, UseCachedFrames, Subtitles, SubtitlesLang, SubtitlesUseLang
    global User_FPS, DisableDynamicSkip, DebugFPS

    local_file = None
    youtube_link = None

    idx = 0
    while idx < len(args):
        arg = args[idx]

        if arg in ('-h', '-help'):
            print_help()
            sys.exit(0)

        elif arg == '-y':
            YT = True
            idx += 1
            if idx < len(args):
                youtube_link = args[idx]
                idx += 1

        elif arg == '-c':
            UseCachedFrames = True
            idx += 1

        elif arg == '-sub':
            Subtitles = True
            idx += 1
            # check if next arg is a language code
            if idx < len(args) and not args[idx].startswith('-'):
                SubtitlesLang = args[idx]
                SubtitlesUseLang = True
                idx += 1

        elif arg == '-f':
            idx += 1
            if idx < len(args):
                try:
                    User_FPS = float(args[idx])
                except ValueError:
                    print("Invalid -f argument.")
                    sys.exit(1)
                idx += 1

        elif arg == '-noskip':
            DisableDynamicSkip = True
            idx += 1

        elif arg == '-debug':
            DebugFPS = True
            idx += 1

        else:
            # local file
            local_file = arg
            idx += 1

    return local_file, youtube_link

################################################################################
# ----------------------------- VLC SETUP ------------------------------------- #
################################################################################

def get_vlc_player(path):
    instance = vlc.Instance('--intf=dummy', '--no-video', '--quiet')
    player = instance.media_player_new()
    media = instance.media_new(path)
    player.set_media(media)
    return player

################################################################################
# ----------------------------- MAIN ------------------------------------------ #
################################################################################

def main():
    global stdscr

    args = sys.argv[1:]
    if not args:
        print_help()
        sys.exit(0)

    local_file, youtube_link = parse_args(args)

    # If not playing from YouTube, we can init curses right away
    if not YT:
        stdscr = curses.initscr()
        start_curses()

    try:
        # If user didn't specify -c, we do extraction + resizing
        if not UseCachedFrames:
            total_frames = get_video_frames(local_file, youtube_link)
            if YT and Subtitles:
                stdscr.addstr("Getting video captions\n")
                stdscr.refresh()
                get_captions(youtube_link)
                stdscr.addstr("Got captions\n")
                stdscr.refresh()
            resize_images(total_frames)
        else:
            # Skip extracting/resizing
            stdscr.addstr("Using cached frames in 'resized/' folder.\n")
            stdscr.refresh()

            # We still want metadata for total_frames
            total_frames = get_video_metadata(local_file, youtube_link)
            if YT and Subtitles:
                stdscr.addstr("Getting video captions\n")
                stdscr.refresh()
                get_captions(youtube_link)
                stdscr.addstr("Got captions\n")
                stdscr.refresh()

        # Precompute ASCII from resized frames
        ascii_frames = precompute_ascii_frames(total_frames)

        # Setup audio
        if YT:
            audio_source = "YouTubeTemporary/video.mp4"
        else:
            audio_source = local_file

        player = get_vlc_player(audio_source)

        # Draw frames
        draw_images(total_frames, ascii_frames, player)

    except KeyboardInterrupt:
        stop_audio_and_curses()
        sys.exit(0)
    except Exception as e:
        stop_audio_and_curses()
        raise e

    stop_curses()

################################################################################
# --------------------- VIDEO METADATA (FOR -c MODE) ------------------------- #
################################################################################

def get_video_metadata(local_file, youtube_link):
    """
    If skipping extraction/resizing, we still need Video_FPS and Video_Frames
    so we know how many frames are expected.
    """
    global Video_FPS, Video_Frames, stdscr

    if YT:
        path = "YouTubeTemporary/video.mp4"
    else:
        path = local_file

    cap = cv2.VideoCapture(path)
    Video_FPS = int(cap.get(cv2.CAP_PROP_FPS))
    Video_Frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    stdscr.addstr(f"Metadata => FPS={Video_FPS}, Frames={Video_Frames}\n")
    stdscr.refresh()
    return Video_Frames

################################################################################
# --------------------- EXTRACT FRAMES (IF NOT -c) --------------------------- #
################################################################################

def get_video_frames(local_file, youtube_link):
    global stdscr, Video_FPS, Video_Frames

    if not YT:
        cap = cv2.VideoCapture(local_file)
    else:
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_link])
            cap = cv2.VideoCapture("YouTubeTemporary/video.mp4")

        stdscr = curses.initscr()
        start_curses()

    stdscr.addstr("Loading frames\n")
    stdscr.refresh()

    Video_FPS = int(cap.get(cv2.CAP_PROP_FPS))
    Video_Frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    loading_bar = LoadingBar(Video_Frames, barLength=stdscr.getmaxyx()[1] - 2)

    success, image = cap.read()
    count = 0
    y, x = curses.getsyx()

    while success:
        stdscr.addstr(y, x, f"Frame {count} / {Video_Frames - 1}")
        loading_bar.progress = count
        stdscr.addstr(f"\n{loading_bar.display()}\n")
        stdscr.refresh()

        cv2.imwrite(f"frames/frame{count}.jpg", image)
        success, image = cap.read()
        count += 1

    cap.release()

    stdscr.addch("\n")
    stdscr.addstr("Finished loading frames\n")
    stdscr.refresh()
    return count

################################################################################
# -------------------------- RESIZE IMAGES ------------------------------------ #
################################################################################

def resize_images(framesAmount):
    stdscr.addstr("Started resizing images\n")
    stdscr.refresh()
    y, x = stdscr.getyx()

    resize_bar = LoadingBar(Video_Frames, barLength=stdscr.getmaxyx()[1] - 2)

    for i in range(framesAmount):
        stdscr.move(y, x)
        resized_image = resize_image(i, y, x)
        resized_image.save(f"resized/resized{i}.jpg")

        resize_bar.progress = i
        stdscr.addstr(f"\n{resize_bar.display()}\n")

    stdscr.addstr("\nResized images\n")
    stdscr.refresh()

def resize_image(index, y, x):
    stdscr.addstr(y, x, f"Resized Image {index}")
    stdscr.refresh()

    term_height, term_width = stdscr.getmaxyx()
    new_height = max(1, term_height - 1)
    new_width = max(1, term_width)

    im = Image.open(f"frames/frame{index}.jpg")
    im = im.convert('L')
    im = im.resize((new_width, new_height))
    return im

################################################################################
# ---------------------- PRECOMPUTE ASCII OFFLINE ---------------------------- #
################################################################################

def precompute_ascii_frames(framesAmount):
    stdscr.addstr("Precomputing ASCII for all frames...\n")
    stdscr.refresh()

    term_height, term_width = stdscr.getmaxyx()
    precomputed = []

    precompute_bar = LoadingBar(framesAmount, barLength=term_width - 2)
    y, x = stdscr.getyx()

    for i in range(framesAmount):
        stdscr.move(y, x)
        stdscr.addstr(f"Converting frame {i}/{framesAmount-1}\n")

        path = f"resized/resized{i}.jpg"
        img = Image.open(path)
        pixels = img.load()

        ascii_lines = []
        for row in range(img.height):
            row_chars = []
            for col in range(img.width):
                val = pixels[col, row]
                idx_char = val // 25
                row_chars.append(chars[int(idx_char)])
            ascii_lines.append("".join(row_chars))

        precomputed.append(ascii_lines)

        precompute_bar.progress = i
        stdscr.addstr(precompute_bar.display() + "\n")
        stdscr.refresh()

    stdscr.addstr("Finished precomputing ASCII.\n")
    stdscr.refresh()
    return precomputed

################################################################################
# -------------------------- DRAW IMAGES / PLAYBACK --------------------------- #
################################################################################

def draw_images(framesAmount, ascii_frames, player):
    """
    Main playback loop:
      - Uses a skip-factor if user_fps < video_fps to avoid slow-motion
        (we skip frames so total playback time ~ real audio length).
      - Optionally does dynamic skipping (unless disabled by -noskip).
      - If -debug is set, show real-time FPS in the top-right corner in GREEN.
    """
    stdscr.addstr("Press any key to start drawing\n")
    stdscr.refresh()
    stdscr.getch()

    # Start audio
    player.play()

    # Determine final display FPS
    effective_fps = User_FPS if User_FPS else Video_FPS
    if effective_fps <= 0:
        effective_fps = Video_FPS  # fallback

    # Compute skip_factor so total play time = frames / video_fps
    skip_factor = max(1, int(round(Video_FPS / effective_fps)))

    # Time-based scheduling for dynamic skipping
    start_time = time.time()
    skip_threshold = 0.05  # 50 ms behind => skip to catch up

    # For debug FPS
    last_fps_time = time.time()
    frames_in_second = 0
    displayed_fps = 0.0

    frame_idx = 0
    while frame_idx < framesAmount:
        t_ideal = (frame_idx / Video_FPS)
        now = time.time() - start_time

        # If dynamic skipping is enabled and we are behind schedule, skip
        if not DisableDynamicSkip:
            if now > (t_ideal + skip_threshold):
                frame_idx += skip_factor
                continue

        # If we're a bit early, sleep
        if now < t_ideal:
            time.sleep(t_ideal - now)

        # Actually draw the frame
        ascii_lines = ascii_frames[frame_idx]
        for row_idx, line_text in enumerate(ascii_lines):
            stdscr.move(row_idx, 0)
            stdscr.addstr(line_text)

        # Subtitles, if YT
        if YT and Subtitles:
            get_caption_at_frame(frame_idx)

        # If debug is on, compute live FPS
        frames_in_second += 1
        current_time = time.time()
        if (current_time - last_fps_time) >= 1.0:
            displayed_fps = frames_in_second / (current_time - last_fps_time)
            frames_in_second = 0
            last_fps_time = current_time

        # If debug is on, show in the top-right corner in GREEN
        if DebugFPS:
            s = f"FPS:{displayed_fps:.2f}"
            max_y, max_x = stdscr.getmaxyx()
            debug_col = max_x - len(s) - 1
            # Use color pair (GREEN_PAIR_IDX) for green text
            stdscr.addstr(0, debug_col, s, curses.color_pair(GREEN_PAIR_IDX))

        stdscr.refresh()

        # Move to next "displayed" frame by skip_factor
        frame_idx += skip_factor

    # Stop audio
    player.stop()

################################################################################
# ------------------------- CAPTIONS FOR YOUTUBE ----------------------------- #
################################################################################

def get_captions(youtube_link):
    global CaptionsArray, SubtitlesUseLang, SubtitlesLang

    video_id = extract.video_id(youtube_link)
    if not SubtitlesUseLang:
        CaptionsArray = YouTubeTranscriptApi.get_transcript(video_id)
    else:
        CaptionsArray = YouTubeTranscriptApi.get_transcript(video_id, languages=[SubtitlesLang])

def get_caption_at_frame(frame_idx):
    # Clear the subtitle line
    for col in range(stdscr.getmaxyx()[1]):
        stdscr.addstr(stdscr.getmaxyx()[0] - 1, col, " ")

    time_needed = frame_idx / Video_FPS
    global PreviousCaptionsArrayIndex
    time_passed = CaptionsArray[0]["start"]

    text = ""
    found_new_caption = False
    for i in range(len(CaptionsArray)):
        time_passed += CaptionsArray[i]["duration"]
        if int(time_passed) == int(time_needed):
            PreviousCaptionsArrayIndex = i
            text = CaptionsArray[i]["text"]
            found_new_caption = True
            break

    if not found_new_caption:
        text = CaptionsArray[PreviousCaptionsArrayIndex]["text"]

    cap_row = stdscr.getmaxyx()[0] - 1
    cap_col = int(stdscr.getmaxyx()[1] / 2 - len(text) / 2)
    stdscr.addstr(cap_row, cap_col, text)

################################################################################
# ----------------------------- CURSES ---------------------------------------- #
################################################################################

def start_curses():
    curses.curs_set(0)
    curses.noecho()
    curses.cbreak()
    curses.start_color()
    # Initialize a green color pair for debug text
    curses.init_pair(GREEN_PAIR_IDX, curses.COLOR_GREEN, curses.COLOR_BLACK)

def stop_curses():
    curses.curs_set(1)
    curses.echo()
    curses.nocbreak()

def stop_audio_and_curses():
    try:
        stop_curses()
    except:
        pass
    # Stop any active VLC instance
    vlc.Instance().media_player_new().stop()

################################################################################
# ----------------------------- LOADING BAR ----------------------------------- #
################################################################################

class LoadingBar:
    def __init__(self, total, borderChars=["[", "]"], progressChar="#", emptyChar=" ", barLength=50):
        self.total = total
        self.progress = 0
        self.borderChars = borderChars
        self.progressChar = progressChar
        self.emptyChar = emptyChar
        self.barLength = barLength

    def display(self):
        if self.total == 0:
            return f"{self.borderChars[0]}{self.borderChars[1]}"

        done = round((self.progress / self.total) * self.barLength)
        toPrint = self.borderChars[0]
        toPrint += self.progressChar * done
        toPrint += self.emptyChar * (self.barLength - done)
        toPrint += self.borderChars[1]
        return toPrint

################################################################################
# ----------------------------- ENTRY POINT ----------------------------------- #
################################################################################

if __name__ == "__main__":
    main()
