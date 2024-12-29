#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import time
import math
import curses
import cv2
from PIL import Image
import yt_dlp as youtube_dl
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

YT = False               # True if playing from YouTube
UseCachedFrames = False  # If True, skip extraction/resizing (must have existing resized/*.png)
WriteFrames = False      # If True, store frames to disk as .png (lossless)
Subtitles = False        # YouTube subtitles if -sub
SubtitlesLang = None
SubtitlesUseLang = False

DisableDynamicSkip = False
DebugFPS = False
ColorMode = False           # If True, each pixel is a colored block
PreviousCaptionsArrayIndex = 0

Video_FPS = None
Video_Frames = None
stdscr = None
User_FPS = None

# ASCII grayscale map for shading (if ColorMode=False)
chars_gray = ["B","S","#","&","@","$","%","*","!","."," "]

################################################################################
# 256-Color Support
################################################################################

COLOR_PAIR_CACHE = {}
NEXT_COLOR_PAIR_ID = 1

def xterm_256_index(r, g, b):
    """
    Convert (r,g,b) -> xterm-256 index.
    Indices 16..231 form a 6x6x6 color cube;
    Indices 232..255 are a 24-step grayscale ramp.
    """
    if r == g == b:
        gray_level = r
        gray_index = int(round(gray_level / 255.0 * 23))
        return 232 + gray_index

    R = int(round(r / 255.0 * 5))
    G = int(round(g / 255.0 * 5))
    B = int(round(b / 255.0 * 5))
    return 16 + (36 * R) + (6 * G) + B

def get_color_pair(fg_idx, bg_idx):
    global NEXT_COLOR_PAIR_ID

    key = (fg_idx, bg_idx)
    if key in COLOR_PAIR_CACHE:
        return COLOR_PAIR_CACHE[key]

    pair_id = NEXT_COLOR_PAIR_ID
    curses.init_pair(pair_id, fg_idx, bg_idx)
    COLOR_PAIR_CACHE[key] = pair_id
    NEXT_COLOR_PAIR_ID += 1
    return pair_id

################################################################################
# CLI Parsing
################################################################################

def print_help():
    help_text = f"""
Usage: {sys.argv[0]} [options] <local_file> or -y <YouTubeLink>

Options:
  -y <link>    Play a YouTube video (downloads it first).
  -c           Use cached frames (skip extraction/resizing from disk).
               (Note: -c requires that you previously used -write so
               'frames/' and 'resized/' are populated with .png files.)
  -write       Store frames on disk in PNG format (lossless). This creates
               two loading bars: one for extraction, one for resizing.
               Without this, frames are handled purely in memory (one bar).
  -sub [lang]  Enable YouTube subtitles; optional language code.
  -f <fps>     Set a custom ASCII framerate (displays fewer frames per second).
               Audio still plays at normal speed (frames are skipped).
  -noskip      Disable dynamic skipping (video may get out of sync).
  -debug       Show live FPS (frames drawn per second) top-right.
  -color       Enable color approximation (each pixel is a colored block).
  -h, -help    Show this help message and exit.

Examples:
  python {sys.argv[0]} movie.mp4
  python {sys.argv[0]} -y https://www.youtube.com/watch?v=XYZ -sub en -color -f 10
  python {sys.argv[0]} -write myvideo.mp4
  python {sys.argv[0]} -c  # Only works if you previously used -write
"""
    print(help_text)

def parse_args(args):
    global YT, UseCachedFrames, WriteFrames, Subtitles, SubtitlesLang, SubtitlesUseLang
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
        elif arg == '-write':
            WriteFrames = True
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
            # No cached frames => we need to generate them
            if WriteFrames:
                # 1) Extract all frames => frames/*.png
                total_frames = get_video_frames_png(local_file, youtube_link)
                if YT and Subtitles:
                    stdscr.addstr("Getting video captions\n")
                    stdscr.refresh()
                    get_captions(youtube_link)
                    stdscr.addstr("Got captions\n")
                    stdscr.refresh()

                # 2) Resize => resized/*.png
                resize_images_png(total_frames)

                # 3) Precompute from "resized/" folder
                ascii_frames = precompute_ascii_frames_from_disk(total_frames)
            else:
                # Single pass: load each frame, resize in memory, precompute ASCII, free memory
                # => single bar
                ascii_frames, total_frames = load_resize_precompute_in_memory(local_file, youtube_link)
                if YT and Subtitles:
                    stdscr.addstr("Getting video captions\n")
                    stdscr.refresh()
                    get_captions(youtube_link)
                    stdscr.addstr("Got captions\n")
                    stdscr.refresh()
        else:
            # -c => read from resized/*.png
            # Must have previously run with -write
            stdscr.addstr("Using cached frames in 'resized/' folder.\n")
            stdscr.refresh()

            total_frames = get_video_metadata(local_file, youtube_link)
            if YT and Subtitles:
                stdscr.addstr("Getting video captions\n")
                stdscr.refresh()
                get_captions(youtube_link)
                stdscr.addstr("Got captions\n")
                stdscr.refresh()

            ascii_frames = precompute_ascii_frames_from_disk(total_frames)

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
# Frame Extraction (PNG, Lossless)
################################################################################

def get_video_frames_png(local_file, youtube_link):
    """
    Loads frames from the video, saves each as frames/frame{i}.png (lossless).
    Two-step approach with separate function for resizing.
    """
    global stdscr, Video_FPS, Video_Frames

    if not YT:
        cap = cv2.VideoCapture(local_file)
    else:
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_link])
            cap = cv2.VideoCapture("YouTubeTemporary/video.mp4")

        stdscr = curses.initscr()
        start_curses()

    stdscr.addstr("Loading frames (PNG)\n")
    stdscr.refresh()

    Video_FPS = int(cap.get(cv2.CAP_PROP_FPS))
    Video_Frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    loading_bar = LoadingBar(Video_Frames, barLength=stdscr.getmaxyx()[1] - 2)

    success, frame = cap.read()
    count = 0
    y, x = curses.getsyx()

    while success:
        stdscr.addstr(y, x, f"Frame {count} / {Video_Frames - 1}\n")
        loading_bar.progress = count
        stdscr.addstr(loading_bar.display() + "\n")
        stdscr.refresh()

        # Save as PNG (lossless)
        cv2.imwrite(f"frames/frame{count}.png", frame, [cv2.IMWRITE_PNG_COMPRESSION, 0])

        success, frame = cap.read()
        count += 1

    cap.release()

    stdscr.addstr("\nFinished loading frames => frames/*.png\n")
    stdscr.refresh()
    return count

################################################################################
# Resizing => resized/*.png
################################################################################

def resize_images_png(framesAmount):
    """
    Reads frames/frame{i}.png => resizes => saved in resized/resized{i}.png
    """
    global stdscr
    stdscr.addstr("Started resizing images (PNG)\n")
    stdscr.refresh()
    y, x = stdscr.getyx()

    resize_bar = LoadingBar(framesAmount, barLength=stdscr.getmaxyx()[1] - 2)

    for i in range(framesAmount):
        stdscr.move(y, x)
        resized_image = resize_image_png(i)
        resized_image.save(f"resized/resized{i}.png", "PNG")

        resize_bar.progress = i
        stdscr.addstr("\n" + resize_bar.display() + "\n")

    stdscr.addstr("\nResized images => resized/*.png\n")
    stdscr.refresh()

def resize_image_png(index):
    """
    Loads frames/frame{index}.png => resize => return PIL image
    """
    term_height, term_width = stdscr.getmaxyx()
    new_height = max(1, term_height - 1)
    new_width = max(1, term_width)

    im = Image.open(f"frames/frame{index}.png")
    if ColorMode:
        im = im.convert("RGB")
    else:
        im = im.convert("L")

    # NEAREST to avoid blur
    im = im.resize((new_width, new_height), resample=Image.NEAREST)
    return im

################################################################################
# Single-Pass In-Memory (No Write)
################################################################################

def load_resize_precompute_in_memory(local_file, youtube_link):
    """
    If not writing, we do a single pass:
      1) read each frame from the video
      2) convert/resize in memory
      3) convert to ASCII
      4) discard the frame to free memory
    We only store the final ASCII data, not the images.
    Returns (ascii_frames, total_frames).
    """
    global stdscr, Video_FPS, Video_Frames

    if not YT:
        cap = cv2.VideoCapture(local_file)
    else:
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_link])
            cap = cv2.VideoCapture("YouTubeTemporary/video.mp4")

        stdscr = curses.initscr()
        start_curses()

    stdscr.addstr("Loading & Precomputing frames (IN MEMORY, single pass)\n")
    stdscr.refresh()

    Video_FPS = int(cap.get(cv2.CAP_PROP_FPS))
    Video_Frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    load_bar = LoadingBar(Video_Frames, barLength=stdscr.getmaxyx()[1] - 2)
    ascii_frames = []

    term_height, term_width = stdscr.getmaxyx()
    new_height = max(1, term_height - 1)
    new_width = max(1, term_width)

    y, x = curses.getsyx()
    count = 0

    success, frame = cap.read()
    while success:
        stdscr.move(y, x)
        stdscr.addstr(f"Frame {count} / {Video_Frames - 1}\n")
        load_bar.progress = count
        stdscr.addstr(load_bar.display() + "\n")
        stdscr.refresh()

        # 1) Convert to PIL
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        im_pil = Image.fromarray(frame_rgb)

        # 2) Color or Gray
        if ColorMode:
            im_pil = im_pil.convert("RGB")
        else:
            im_pil = im_pil.convert("L")

        # 3) Resize
        im_pil = im_pil.resize((new_width, new_height), resample=Image.NEAREST)

        # 4) Convert to ASCII immediately
        frame_data = []
        pixels = im_pil.load()
        for row in range(im_pil.height):
            row_data = []
            for col in range(im_pil.width):
                if ColorMode:
                    r, g, b = pixels[col, row]
                    color_idx = xterm_256_index(r, g, b)
                    pair_id = get_color_pair(color_idx, color_idx)
                    row_data.append(('█', pair_id))
                else:
                    val = pixels[col, row]
                    char_idx = int(val // 25)
                    ascii_char = chars_gray[char_idx]
                    row_data.append(ascii_char)
            frame_data.append(row_data)

        ascii_frames.append(frame_data)

        # free memory by discarding 'frame' and 'im_pil'
        frame = None
        im_pil = None

        success, frame = cap.read()
        count += 1

    cap.release()
    stdscr.addstr("\nFinished single-pass in-memory load+precompute.\n")
    stdscr.refresh()
    return (ascii_frames, count)

################################################################################
# Precompute ASCII from Disk => 'resized/*.png'
################################################################################

def precompute_ascii_frames_from_disk(framesAmount):
    """
    Reads from 'resized/resized{i}.png' => convert to ASCII => returns list of frames.
    """
    global stdscr

    stdscr.addstr("Precomputing ASCII frames from disk...\n")
    stdscr.refresh()

    term_height, term_width = stdscr.getmaxyx()
    precomputed = []

    bar = LoadingBar(framesAmount, barLength=term_width - 2)
    y, x = stdscr.getyx()

    for i in range(framesAmount):
        stdscr.move(y, x)
        stdscr.addstr(f"Converting frame {i}/{framesAmount-1}\n")

        img_path = f"resized/resized{i}.png"
        img = Image.open(img_path)
        pixels = img.load()

        frame_data = []
        for row in range(img.height):
            row_data = []
            for col in range(img.width):
                if ColorMode:
                    r, g, b = pixels[col, row]
                    color_idx = xterm_256_index(r, g, b)
                    pair_id = get_color_pair(color_idx, color_idx)
                    row_data.append(('█', pair_id))
                else:
                    val = pixels[col, row]
                    char_idx = int(val // 25)
                    ascii_char = chars_gray[char_idx]
                    row_data.append(ascii_char)

            frame_data.append(row_data)

        precomputed.append(frame_data)

        bar.progress = i
        stdscr.addstr(bar.display() + "\n")
        stdscr.refresh()

    stdscr.addstr("Finished precomputing from disk.\n")
    stdscr.refresh()
    return precomputed

################################################################################
# Video Metadata
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

    skip_factor = max(1, int(round(Video_FPS / effective_fps)))

    start_time = time.time()
    skip_threshold = 0.05

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

        frame_data = ascii_frames[frame_idx]
        for row_idx, row_data in enumerate(frame_data):
            for col_idx, px_data in enumerate(row_data):
                if ColorMode:
                    (char, pair_id) = px_data
                    stdscr.addstr(row_idx, col_idx, char, curses.color_pair(pair_id))
                else:
                    stdscr.addstr(row_idx, col_idx, px_data)

        if YT and Subtitles:
            get_caption_at_frame(frame_idx)

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

            green_idx = xterm_256_index(0, 255, 0)
            black_idx = 0
            debug_pair = get_color_pair(green_idx, black_idx)
            stdscr.addstr(0, debug_col, s, curses.color_pair(debug_pair))

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
    col = max(0, int(stdscr.getmaxyx()[1] / 2 - len(text) / 2))
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
