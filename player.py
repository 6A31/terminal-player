#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import time
import math
import curses
import cv2
from PIL import Image
import youtube_dl
import vlc
from pytube import extract
from youtube_transcript_api import YouTubeTranscriptApi

################################################################################
# Global Config & Flags
################################################################################

ydl_opts = {
    'format': 'bestvideo[ext=mp4]+bestaudio[ext=mp4]/mp4',
    'outtmpl': 'YouTubeTemporary/video.%(ext)s',
}

YT = False              # True if playing from YouTube
UseCachedFrames = False # Skip extraction/resizing if -c
Subtitles = False       # YouTube subtitles if -sub
SubtitlesLang = None
SubtitlesUseLang = False

DisableDynamicSkip = False  # If True, don't skip frames to catch up
DebugFPS = False            # If True, show FPS top-right
ColorMode = False           # If True, use color approximation
PreviousCaptionsArrayIndex = 0

Video_FPS = None
Video_Frames = None
stdscr = None
User_FPS = None

# ASCII grayscale map for shading (if not using color)
chars_gray = ["B","S","#","&","@","$","%","*","!","."," "]

# For color logic, we still want a "brightness-based" character, or you can choose block chars
# We'll reuse the same grayscale map for the "character," but pick colors by (R,G,B).
# If you prefer big blocks, you could do char = "█".

################################################################################
# Basic Color Palette (8 color IDs) -> approximate (R,G,B)
################################################################################

# We'll define these as numeric IDs we can init for curses:
C_COLOR_BLACK   = 1
C_COLOR_RED     = 2
C_COLOR_GREEN   = 3
C_COLOR_YELLOW  = 4
C_COLOR_BLUE    = 5
C_COLOR_MAGENTA = 6
C_COLOR_CYAN    = 7
C_COLOR_WHITE   = 8

COLOR_PALETTE = {
    C_COLOR_BLACK:   (0,   0,   0),
    C_COLOR_RED:     (255, 0,   0),
    C_COLOR_GREEN:   (0,   255, 0),
    C_COLOR_YELLOW:  (255, 255, 0),
    C_COLOR_BLUE:    (0,   0,   255),
    C_COLOR_MAGENTA: (255, 0,   255),
    C_COLOR_CYAN:    (0,   255, 255),
    C_COLOR_WHITE:   (255, 255, 255),
}

def closest_curses_color(r, g, b):
    """
    Return which of our 8 color IDs is closest to (r,g,b).
    """
    best_id = C_COLOR_BLACK
    best_dist = float('inf')
    for color_id, (cr, cg, cb) in COLOR_PALETTE.items():
        dist = (r - cr)**2 + (g - cg)**2 + (b - cb)**2
        if dist < best_dist:
            best_dist = dist
            best_id = color_id
    return best_id

################################################################################
# CLI Parsing
################################################################################

def print_help():
    help_text = f"""
Usage: {sys.argv[0]} [options] <local_file> or -y <YouTubeLink>

Options:
  -y <link>    Play a YouTube video (downloads it first).
  -c           Use cached frames (skip extraction & resizing).
  -sub [lang]  Enable YouTube subtitles; optional language code.
  -f <fps>     Set a custom ASCII framerate (displays fewer frames per second).
               Audio still plays at normal speed (frames are skipped).
  -noskip      Disable dynamic skipping. If the program falls behind schedule,
               it won't skip frames to catch up (video may get out of sync).
  -debug       Show live FPS (frames drawn per second) top-right.
  -color       Enable color approximation (8-color ASCII).
  -h, -help    Show this help message and exit.

Examples:
  # Local file, normal run
  python {sys.argv[0]} movie.mp4

  # YouTube, with default subtitles, color, 10 FPS:
  python {sys.argv[0]} -y https://www.youtube.com/watch?v=XYZ -sub -color -f 10
"""
    print(help_text)

def parse_args(args):
    global YT, UseCachedFrames, Subtitles, SubtitlesLang, SubtitlesUseLang
    global User_FPS, DisableDynamicSkip, DebugFPS, ColorMode

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
        elif arg == '-color':
            ColorMode = True
            idx += 1
        else:
            # local file
            local_file = arg
            idx += 1

    return local_file, youtube_link

################################################################################
# VLC Setup
################################################################################

def get_vlc_player(path):
    instance = vlc.Instance('--intf=dummy', '--no-video', '--quiet')
    player = instance.media_player_new()
    media = instance.media_new(path)
    player.set_media(media)
    return player

################################################################################
# Main
################################################################################

def main():
    global stdscr

    args = sys.argv[1:]
    if not args:
        print_help()
        sys.exit(0)

    local_file, youtube_link = parse_args(args)

    if not YT:
        stdscr = curses.initscr()
        start_curses()

    try:
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
            stdscr.addstr("Using cached frames in 'resized/' folder.\n")
            stdscr.refresh()

            total_frames = get_video_metadata(local_file, youtube_link)
            if YT and Subtitles:
                stdscr.addstr("Getting video captions\n")
                stdscr.refresh()
                get_captions(youtube_link)
                stdscr.addstr("Got captions\n")
                stdscr.refresh()

        # Precompute frames: either color or grayscale
        ascii_frames = precompute_ascii_frames(total_frames)

        # Setup audio
        if YT:
            audio_source = "YouTubeTemporary/video.mp4"
        else:
            audio_source = local_file

        player = get_vlc_player(audio_source)
        draw_images(total_frames, ascii_frames, player)

    except KeyboardInterrupt:
        stop_audio_and_curses()
        sys.exit(0)
    except Exception as e:
        stop_audio_and_curses()
        raise e

    stop_curses()

################################################################################
# Video Metadata (For -c mode)
################################################################################

def get_video_metadata(local_file, youtube_link):
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
# Frame Extraction
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
# Resizing
################################################################################

def resize_images(framesAmount):
    stdscr.addstr("Started resizing images\n")
    stdscr.refresh()
    y, x = stdscr.getyx()

    resize_bar = LoadingBar(Video_Frames, barLength=stdscr.getmaxyx()[1] - 2)

    for i in range(framesAmount):
        stdscr.move(y, x)
        resized_image = resize_image(i, y, x)
        # Save result
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
    # If we are in color mode, convert to RGB, else grayscale
    if ColorMode:
        im = im.convert('RGB')
    else:
        im = im.convert('L')

    im = im.resize((new_width, new_height))
    return im

################################################################################
# Precompute ASCII frames (with or without color)
################################################################################

def precompute_ascii_frames(framesAmount):
    stdscr.addstr("Precomputing ASCII frames...\n")
    stdscr.refresh()

    term_height, term_width = stdscr.getmaxyx()
    precomputed = []

    bar = LoadingBar(framesAmount, barLength=term_width - 2)
    y, x = stdscr.getyx()

    for i in range(framesAmount):
        stdscr.move(y, x)
        stdscr.addstr(f"Converting frame {i}/{framesAmount-1}\n")

        img_path = f"resized/resized{i}.jpg"
        img = Image.open(img_path)
        pixels = img.load()

        frame_data = []
        for row in range(img.height):
            row_data = []
            for col in range(img.width):
                if ColorMode:
                    r, g, b = pixels[col, row]
                    # 1) pick ASCII char based on brightness
                    brightness = (r + g + b) / 3
                    char_idx = int(brightness // 25)  # 0..10
                    ascii_char = chars_gray[char_idx]

                    # 2) find color ID from 8-color palette
                    color_id = closest_curses_color(r, g, b)
                    # Store (char, color_id)
                    row_data.append((ascii_char, color_id))
                else:
                    # grayscale
                    val = pixels[col, row]
                    char_idx = int(val // 25)  # 0..10
                    ascii_char = chars_gray[char_idx]
                    # Store just char (colorless)
                    row_data.append(ascii_char)
            frame_data.append(row_data)

        precomputed.append(frame_data)

        bar.progress = i
        stdscr.addstr(bar.display() + "\n")
        stdscr.refresh()

    stdscr.addstr("Finished precomputing.\n")
    stdscr.refresh()
    return precomputed

################################################################################
# Drawing / Playback
################################################################################

def draw_images(framesAmount, ascii_frames, player):
    stdscr.addstr("Press any key to start drawing\n")
    stdscr.refresh()
    stdscr.getch()

    player.play()

    effective_fps = User_FPS if User_FPS else Video_FPS
    if effective_fps <= 0:
        effective_fps = Video_FPS

    # skip_factor if user_fps < video_fps
    skip_factor = max(1, int(round(Video_FPS / effective_fps)))

    start_time = time.time()
    skip_threshold = 0.05  # 50ms behind => skip

    last_fps_time = time.time()
    frames_in_second = 0
    displayed_fps = 0.0

    frame_idx = 0
    while frame_idx < framesAmount:
        t_ideal = frame_idx / Video_FPS
        now = time.time() - start_time

        if not DisableDynamicSkip:
            if now > t_ideal + skip_threshold:
                frame_idx += skip_factor
                continue

        if now < t_ideal:
            time.sleep(t_ideal - now)

        # Draw the frame
        # ascii_frames[frame_idx] is a list of rows
        # row_data is either a list of chars or a list of (char, color_id) if ColorMode
        frame_data = ascii_frames[frame_idx]
        for row_idx, row_data in enumerate(frame_data):
            for col_idx, px_data in enumerate(row_data):
                if ColorMode:
                    (char, color_id) = px_data
                    stdscr.addstr(row_idx, col_idx, char, curses.color_pair(color_id))
                else:
                    # grayscale
                    stdscr.addstr(row_idx, col_idx, px_data)

        if YT and Subtitles:
            get_caption_at_frame(frame_idx)

        # Debug FPS
        frames_in_second += 1
        current_time = time.time()
        if current_time - last_fps_time >= 1.0:
            displayed_fps = frames_in_second / (current_time - last_fps_time)
            frames_in_second = 0
            last_fps_time = current_time

        if DebugFPS:
            s = f"FPS:{displayed_fps:.2f}"
            max_y, max_x = stdscr.getmaxyx()
            debug_col = max_x - len(s) - 1
            # Let's color it green. You could define a custom color pair if you want.
            # We'll just do curses.COLOR_GREEN on black for demonstration if available.
            # If we haven't init a special pair for green, let's do color 2 => red? Actually let's do color 3 => green
            # Or we can re-use the color_id approach from above. We'll do a simpler approach:
            stdscr.addstr(0, debug_col, s, curses.color_pair(C_COLOR_GREEN))

        stdscr.refresh()
        frame_idx += skip_factor

    player.stop()

################################################################################
# Captions
################################################################################

def get_captions(youtube_link):
    global CaptionsArray
    video_id = extract.video_id(youtube_link)
    if not SubtitlesUseLang:
        CaptionsArray = YouTubeTranscriptApi.get_transcript(video_id)
    else:
        CaptionsArray = YouTubeTranscriptApi.get_transcript(video_id, languages=[SubtitlesLang])

def get_caption_at_frame(frame_idx):
    # Clear last line
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

    row = stdscr.getmaxyx()[0] - 1
    col = int(stdscr.getmaxyx()[1] / 2 - len(text) / 2)
    stdscr.addstr(row, col, text)

################################################################################
# Curses Setup & Teardown
################################################################################

def start_curses():
    curses.curs_set(0)
    curses.noecho()
    curses.cbreak()
    curses.start_color()
    curses.use_default_colors()

    # Initialize the 8 color pairs
    curses.init_pair(C_COLOR_BLACK,   curses.COLOR_BLACK,   -1)
    curses.init_pair(C_COLOR_RED,     curses.COLOR_RED,     -1)
    curses.init_pair(C_COLOR_GREEN,   curses.COLOR_GREEN,   -1)
    curses.init_pair(C_COLOR_YELLOW,  curses.COLOR_YELLOW,  -1)
    curses.init_pair(C_COLOR_BLUE,    curses.COLOR_BLUE,    -1)
    curses.init_pair(C_COLOR_MAGENTA, curses.COLOR_MAGENTA, -1)
    curses.init_pair(C_COLOR_CYAN,    curses.COLOR_CYAN,    -1)
    curses.init_pair(C_COLOR_WHITE,   curses.COLOR_WHITE,   -1)

def stop_curses():
    curses.curs_set(1)
    curses.echo()
    curses.nocbreak()

def stop_audio_and_curses():
    try:
        stop_curses()
    except:
        pass
    vlc.Instance().media_player_new().stop()

################################################################################
# LoadingBar
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
# Entry Point
################################################################################

if __name__ == "__main__":
    main()
