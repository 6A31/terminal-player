#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import time
import math
import curses
import cv2
import os
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
YT = False
UseCachedFrames = False
WriteFrames = False
Subtitles = False
SubtitlesLang = None
SubtitlesUseLang = False
DisableDynamicSkip = False
DebugFPS = False
ColorMode = False
PreviousCaptionsArrayIndex = 0
Video_FPS = None
Video_Frames = None
stdscr = None
User_FPS = None
Precompute = True  # Default is True; set to False when -nocompute is used
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
    """
    Return a curses color pair ID for the given FG/BG xterm-256 indices.
    """
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
               Requires that you previously used -write so 'resized/' is populated
               with .png files and metadata.
               A local video file or YouTube link must still be provided.
  -write       Store frames on disk in PNG format (lossless). This creates
               two loading bars: one for extraction, one for resizing.
               Without this, frames are handled purely in memory (one bar).
  -nocompute   Do not precompute frames into memory; compute and render frames live during playback.
               This reduces memory usage, suitable for larger videos.
               Not compatible with -write or -c.
  -sub [lang]  Enable YouTube subtitles; optional language code.
  -f <fps>     Set a custom ASCII framerate (fewer frames per second).
               Audio still plays at normal speed (frames may be skipped).
  -noskip      Disable dynamic skipping (video may get out of sync).
  -debug       Show live FPS (frames drawn per second) top-right.
  -color       Enable color approximation (each pixel is a colored block).
  -h, -help    Show this help message and exit.
Examples:
  python {sys.argv[0]} movie.mp4
  python {sys.argv[0]} -y https://www.youtube.com/watch?v=XYZ -sub en -color -f 10
  python {sys.argv[0]} -write myvideo.mp4
  python {sys.argv[0]} -c myvideo.mp4  # Only works if you previously used -write
"""
    print(help_text)
def parse_args(args):
    """
    Parse command-line arguments and set global flags accordingly.
    Return (local_file, youtube_link).
    """
    global YT, UseCachedFrames, WriteFrames, Subtitles, SubtitlesLang, SubtitlesUseLang
    global User_FPS, DisableDynamicSkip, DebugFPS, ColorMode, Precompute
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
            else:
                print("Error: No YouTube link provided after -y.")
                sys.exit(1)
        elif arg == '-c':
            UseCachedFrames = True
            idx += 1
        elif arg == '-write':
            WriteFrames = True
            idx += 1
        elif arg == '-nocompute':
            Precompute = False
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
            # Assume this is a local file
            local_file = arg
            idx += 1
    if not Precompute and (UseCachedFrames or WriteFrames):
        print("Error: The flag -nocompute cannot be used with -write or -c.")
        sys.exit(1)
    if UseCachedFrames and not (YT or local_file):
        print("Error: A video file or YouTube link must be provided when using -c.")
        sys.exit(1)
    return local_file, youtube_link
################################################################################
# VLC Setup
################################################################################
def get_vlc_player(path):
    """
    Create and return a VLC media player instance for the given video path.
    """
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
    # Error checks...
    if WriteFrames and UseCachedFrames:
        print("Error: The flags -write and -c cannot be used together.")
        sys.exit(1)
    if not UseCachedFrames and not YT and not local_file:
        print("Error: No video file or YouTube link was provided.")
        sys.exit(1)
    if not YT or not Precompute:
        stdscr = curses.initscr()
        start_curses()
    try:
        if not Precompute:
            # Live compute mode
            cap = setup_video_capture(local_file, youtube_link)
            total_frames = get_video_metadata_from_cap(cap)
            if YT and Subtitles:
                stdscr.addstr("Getting video captions\n")
                stdscr.refresh()
                get_captions(youtube_link)
                stdscr.addstr("Got captions\n")
                stdscr.refresh()
            if YT:
                audio_source = "YouTubeTemporary/video.mp4"
            else:
                audio_source = local_file
            player = get_vlc_player(audio_source)
            draw_images_live(cap, total_frames, player)
            cap.release()
        else:
            if not UseCachedFrames:
                if WriteFrames:
                    # 1) Extract frames => frames/*.png
                    total_frames = get_video_frames_png(local_file, youtube_link)
                    # 2) (Optional) get captions if YT and subtitles
                    if YT and Subtitles:
                        stdscr.addstr("Getting video captions\n")
                        stdscr.refresh()
                        get_captions(youtube_link)
                        stdscr.addstr("Got captions\n")
                        stdscr.refresh()
                    # 3) Resize => resized/*.png
                    resize_images_png(total_frames)
                    # 4) Write metadata => resized/metadata.txt
                    write_cache_metadata(local_file, youtube_link, total_frames)
                    # 5) **Precompute ASCII** from disk (now that it exists)
                    ascii_frames = precompute_ascii_frames_from_disk(total_frames)
                else:
                    # Single pass in-memory approach
                    ascii_frames, total_frames = load_resize_precompute_in_memory(local_file, youtube_link)
                    if YT and Subtitles:
                        stdscr.addstr("Getting video captions\n")
                        stdscr.refresh()
                        get_captions(youtube_link)
                        stdscr.addstr("Got captions\n")
                        stdscr.refresh()
            else:
                # Use cached frames => validate, read metadata, load ASCII from 'resized/'
                check_cached_frames(local_file, youtube_link)
                total_frames = get_video_metadata(local_file, youtube_link)
                if YT and Subtitles:
                    stdscr.addstr("Getting video captions\n")
                    stdscr.refresh()
                    get_captions(youtube_link)
                    stdscr.addstr("Got captions\n")
                    stdscr.refresh()
                ascii_frames = precompute_ascii_frames_from_disk(total_frames)
            # Setup audio source
            if YT:
                audio_source = "YouTubeTemporary/video.mp4"
            else:
                audio_source = local_file
            player = get_vlc_player(audio_source)
            draw_images(total_frames, ascii_frames, player)
    except KeyboardInterrupt:
        if not Precompute:
            cap.release()
        stop_audio_and_curses()
        sys.exit(0)
    except Exception as e:
        if not Precompute:
            cap.release()
        stop_audio_and_curses()
        raise e
    if not YT or not Precompute:
        stop_curses()
################################################################################
# Live Compute Helpers
################################################################################
def setup_video_capture(local_file, youtube_link):
    """
    Open video capture from local file or YouTube temp file
    """
    global stdscr
    if YT:
        if not os.path.exists("YouTubeTemporary/video.mp4"):
            stdscr.addstr("Downloading YouTube video...\n")
            stdscr.refresh()
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                ydl.download([youtube_link])
        cap = cv2.VideoCapture("YouTubeTemporary/video.mp4")
    else:
        cap = cv2.VideoCapture(local_file)
    return cap
def get_video_metadata_from_cap(cap):
    """
    Get Video FPS and Frame Count from an open cv2.VideoCapture object
    """
    global Video_FPS, Video_Frames, stdscr
    Video_FPS = cap.get(cv2.CAP_PROP_FPS)
    Video_Frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    stdscr.addstr(f"Metadata => FPS={Video_FPS}, Frames={Video_Frames}\n")
    stdscr.refresh()
    return Video_Frames
def draw_images_live(cap, total_frames, player):
    """
    Play the audio, then loop through frames, processing and drawing them on the fly.
    """
    stdscr.addstr("Press any key to start drawing\n")
    stdscr.refresh()
    stdscr.getch()
    player.play()
    effective_fps = User_FPS if User_FPS else Video_FPS
    if effective_fps <= 0:
        effective_fps = Video_FPS
    # This skip_factor is for dynamic skipping if system lags
    skip_factor = max(1, int(round(Video_FPS / effective_fps)))
    start_time = time.time()
    skip_threshold = 0.05
    last_fps_time = time.time()
    frames_in_second = 0
    displayed_fps = 0.0
    frame_idx = 0
    max_frame_idx = total_frames - 1
    while frame_idx <= max_frame_idx:
        t_ideal = frame_idx / Video_FPS
        now = time.time() - start_time
        if not DisableDynamicSkip:
            if now > t_ideal + skip_threshold:
                frame_idx += skip_factor
                continue
        if now < t_ideal:
            time.sleep(t_ideal - now)
        # Set the position to frame_idx
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        success, frame = cap.read()
        if not success:
            # Cannot read frame, skip
            frame_idx += skip_factor
            continue
        # Process frame
        frame_data = process_frame(frame)
        # Display frame
        for row_idx, row_data in enumerate(frame_data):
            for col_idx, px_data in enumerate(row_data):
                if ColorMode:
                    (char, pair_id) = px_data
                    try:
                        stdscr.addstr(row_idx, col_idx, char, curses.color_pair(pair_id))
                    except curses.error:
                        pass
                else:
                    try:
                        stdscr.addstr(row_idx, col_idx, px_data)
                    except curses.error:
                        pass
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
            try:
                stdscr.addstr(0, debug_col, s, curses.color_pair(debug_pair))
            except curses.error:
                pass
        stdscr.refresh()
        frame_idx += skip_factor
    player.stop()
def process_frame(frame):
    """
    Given a frame (numpy array), resize it, convert to ASCII or color blocks,
    and return frame_data suitable for display.
    """
    term_height, term_width = stdscr.getmaxyx()
    new_height = max(1, term_height - 1)
    new_width = max(1, term_width)
    # Convert to PIL
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    im_pil = Image.fromarray(frame_rgb)
    # Convert to color or grayscale
    if ColorMode:
        im_pil = im_pil.convert("RGB")
    else:
        im_pil = im_pil.convert("L")
    # Resize
    im_pil = im_pil.resize((new_width, new_height), resample=Image.NEAREST)
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
    return frame_data
################################################################################
# Frame Extraction (PNG, Lossless)
################################################################################
def get_video_frames_png(local_file, youtube_link):
    """
    Loads frames from the video, saves each as frames/frame{i}.png (lossless).
    Then do resizing in a separate step.
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
    # Calculate skip factor so we decode fewer frames if -f was supplied
    skip_factor = 1
    if User_FPS and User_FPS > 0:
        if User_FPS < Video_FPS:
            skip_factor = max(1, int(round(Video_FPS / User_FPS)))
    # We'll guess how many frames we keep
    expected_kept_frames = math.ceil(Video_Frames / skip_factor)
    loading_bar = LoadingBar(expected_kept_frames, barLength=stdscr.getmaxyx()[1] - 2)
    success, frame = cap.read()
    count = 0
    y, x = curses.getsyx()
    while success:
        stdscr.addstr(y, x, f"Frame {count} / {expected_kept_frames}\n")
        loading_bar.progress = count
        stdscr.addstr(loading_bar.display() + "\n")
        stdscr.refresh()
        # Save as PNG
        if not os.path.exists("frames"):
            os.makedirs("frames", exist_ok=True)
        cv2.imwrite(f"frames/frame{count}.png", frame, [cv2.IMWRITE_PNG_COMPRESSION, 0])
        count += 1
        # Skip skip_factor - 1 frames
        for _ in range(skip_factor - 1):
            success = cap.grab()
            if not success:
                break
        success, frame = cap.read()
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
    if not os.path.exists("resized"):
        os.makedirs("resized", exist_ok=True)
    resize_bar = LoadingBar(framesAmount, barLength=stdscr.getmaxyx()[1] - 2)
    for i in range(framesAmount):
        stdscr.move(y, x)
        resized_image = resize_image_png(i)
        resized_image.save(f"resized/resized{i}.png", "PNG")
        resize_bar.progress = i
        stdscr.addstr("\n" + resize_bar.display() + "\n")
        stdscr.refresh()
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
      1) read each frame from the video (optionally skipping)
      2) convert/resize in memory
      3) convert to ASCII
      4) discard
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
    # skip factor
    skip_factor = 1
    if User_FPS and User_FPS > 0:
        if User_FPS < Video_FPS:
            skip_factor = max(1, int(round(Video_FPS / User_FPS)))
    expected_kept_frames = math.ceil(Video_Frames / skip_factor)
    load_bar = LoadingBar(expected_kept_frames, barLength=stdscr.getmaxyx()[1] - 2)
    ascii_frames = []
    term_height, term_width = stdscr.getmaxyx()
    new_height = max(1, term_height - 1)
    new_width = max(1, term_width)
    y, x = curses.getsyx()
    kept_count = 0
    success, frame = cap.read()
    while success:
        stdscr.move(y, x)
        stdscr.addstr(f"Frame {kept_count} / {expected_kept_frames}\n")
        load_bar.progress = kept_count
        stdscr.addstr(load_bar.display() + "\n")
        stdscr.refresh()
        # Convert to PIL
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        im_pil = Image.fromarray(frame_rgb)
        # Convert to color or grayscale
        if ColorMode:
            im_pil = im_pil.convert("RGB")
        else:
            im_pil = im_pil.convert("L")
        # Resize
        im_pil = im_pil.resize((new_width, new_height), resample=Image.NEAREST)
        # Convert to ASCII
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
        kept_count += 1
        # Skip skip_factor - 1 frames
        for _ in range(skip_factor - 1):
            success = cap.grab()
            if not success:
                break
        success, frame = cap.read()
    cap.release()
    stdscr.addstr("\nFinished single-pass in-memory load+precompute.\n")
    stdscr.refresh()
    return (ascii_frames, kept_count)
################################################################################
# Write out metadata for caching
################################################################################
def write_cache_metadata(local_file, youtube_link, framesAmount):
    """
    Writes a simple metadata.txt file to 'resized/' so that
    future -c can check the same input file, fps, etc.
    """
    global Video_FPS, User_FPS
    if not os.path.exists("resized"):
        os.makedirs("resized", exist_ok=True)
    input_name = local_file if local_file else youtube_link
    user_fps_str = f"{User_FPS}" if User_FPS else "None"
    with open("resized/metadata.txt", "w") as f:
        f.write(f"InputFile={input_name}\n")
        f.write(f"OriginalFPS={Video_FPS}\n")
        f.write(f"UsedUserFPS={user_fps_str}\n")
        f.write(f"ResizedFrames={framesAmount}\n")
################################################################################
# precomputing for write mode
################################################################################
def precompute_ascii_frames_from_disk(frames_amount):
    """
    Reads each resized/resized{i}.png, converts to ASCII or color, returns list of frames.
    """
    global stdscr
    ascii_frames = []
    term_height, term_width = stdscr.getmaxyx()
    for i in range(frames_amount):
        path = f"resized/resized{i}.png"
        if not os.path.exists(path):
            continue
        im = Image.open(path)
        if ColorMode:
            im = im.convert("RGB")
        else:
            im = im.convert("L")
        frame_data = []
        pixels = im.load()
        for row in range(im.height):
            row_data = []
            for col in range(im.width):
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
    return ascii_frames
################################################################################
# Check cached frames
################################################################################
def check_cached_frames(local_file, youtube_link):
    """
    Ensure that:
      - 'resized/' folder exists
      - 'resized/metadata.txt' exists
      - The InputFile matches (warn if not)
      - The previously used FPS matches the currently requested one (warn if not)
    """
    global stdscr, User_FPS
    if not os.path.isdir("resized"):
        stdscr.addstr("Error: 'resized/' directory not found. You must run with -write first.\n")
        stdscr.refresh()
        sys.exit(1)
    meta_path = "resized/metadata.txt"
    if not os.path.isfile(meta_path):
        stdscr.addstr("Error: 'resized/metadata.txt' not found. Cannot verify caching metadata.\n")
        stdscr.refresh()
        sys.exit(1)
    # Read the metadata file
    metadata = {}
    with open(meta_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            key, value = line.split("=", 1)
            metadata[key] = value
    # Check input file matches
    current_input = local_file if local_file else youtube_link
    if "InputFile" in metadata:
        if metadata["InputFile"] != current_input:
            stdscr.addstr(
                f"Warning: The cached frames were generated from '{metadata['InputFile']}', "
                f"but you are trying to play '{current_input}'.\n"
            )
            stdscr.refresh()
            # We continue, but you could exit if you want stricter enforcement.
    else:
        stdscr.addstr("Warning: No 'InputFile' in metadata.txt. Cannot verify match.\n")
    # Check that if there was a used user FPS, it matches the new one:
    if "UsedUserFPS" in metadata and metadata["UsedUserFPS"] != "None":
        old_fps = float(metadata["UsedUserFPS"])
        if User_FPS and abs(User_FPS - old_fps) > 1e-6:
            stdscr.addstr(
                f"Warning: The cached frames were extracted at {old_fps} FPS, "
                f"but you requested {User_FPS}.\n"
                f"This may cause desync or incorrect playback.\n"
            )
            stdscr.refresh()
################################################################################
# Video Metadata
################################################################################
def get_video_metadata(local_file, youtube_link):
    """
    Return the total number of frames from the specified local file or YouTube temp file.
    Also sets global Video_FPS, Video_Frames.
    """
    global Video_FPS, Video_Frames, stdscr
    if YT:
        path = "YouTubeTemporary/video.mp4"
    else:
        path = local_file
    cap = cv2.VideoCapture(path)
    Video_FPS = cap.get(cv2.CAP_PROP_FPS)
    Video_Frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    stdscr.addstr(f"Metadata => FPS={Video_FPS}, Frames={Video_Frames}\n")
    stdscr.refresh()
    return Video_Frames
################################################################################
# Drawing / Playback
################################################################################
def draw_images(framesAmount, ascii_frames, player):
    """
    Play the audio, then loop through frames (ASCII or colored blocks), drawing
    them in the terminal, optionally skipping frames for real-time performance.
    """
    stdscr.addstr("Press any key to start drawing\n")
    stdscr.refresh()
    stdscr.getch()
    player.play()
    effective_fps = User_FPS if User_FPS else Video_FPS
    if effective_fps <= 0:
        effective_fps = Video_FPS
    # This skip_factor is for dynamic skipping if system lags
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
                    try:
                        stdscr.addstr(row_idx, col_idx, char, curses.color_pair(pair_id))
                    except curses.error:
                        pass
                else:
                    try:
                        stdscr.addstr(row_idx, col_idx, px_data)
                    except curses.error:
                        pass
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
            try:
                stdscr.addstr(0, debug_col, s, curses.color_pair(debug_pair))
            except curses.error:
                pass
        stdscr.refresh()
        frame_idx += skip_factor
    player.stop()
################################################################################
# Captions
################################################################################
def get_captions(youtube_link):
    """
    Download and store the transcript from a YouTube link, in the global CaptionsArray.
    If a subtitle language is specified, use it; otherwise fetch the default.
    """
    global CaptionsArray
    video_id = extract.video_id(youtube_link)
    if not SubtitlesUseLang:
        CaptionsArray = YouTubeTranscriptApi.get_transcript(video_id)
    else:
        CaptionsArray = YouTubeTranscriptApi.get_transcript(video_id, languages=[SubtitlesLang])
def get_caption_at_frame(frame_idx):
    """
    Update and display captions in the last line, based on the current frame's timestamp.
    """
    for col in range(stdscr.getmaxyx()[1]):
        try:
            stdscr.addstr(stdscr.getmaxyx()[0] - 1, col, " ")
        except curses.error:
            pass
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
    try:
        stdscr.addstr(row, col, text)
    except curses.error:
        pass
################################################################################
# Curses Setup & Teardown
################################################################################
def start_curses():
    """
    Configure curses in "visual" mode (no cursor, no echo, etc.).
    """
    curses.curs_set(0)
    curses.noecho()
    curses.cbreak()
    curses.start_color()
    curses.use_default_colors()
def stop_curses():
    """
    Restore terminal from curses mode to normal.
    """
    curses.curs_set(1)
    curses.echo()
    curses.nocbreak()
def stop_audio_and_curses():
    """
    Stop audio and safely restore terminal, ignoring any curses errors.
    """
    try:
        stop_curses()
    except:
        pass
    vlc.Instance().media_player_new().stop()
################################################################################
# LoadingBar
################################################################################
class LoadingBar:
    """
    Simple ASCII loading bar used to indicate progress when extracting or resizing frames.
    """
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