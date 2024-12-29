# ASCII Video Player (256-Color Edition)

This Python script converts any local or YouTube-based video into ASCII art rendered in your terminal. It supports **256-color** mode for richer color approximation.

## Features

- **Local or YouTube Videos**: Provide a local file or use `-y <URL>` to download and play from YouTube.  
- **Full Terminal Playback**: Streams frames as ASCII art in your terminal while playing audio via VLC.  
- **256-Color Mode**: Dynamically approximates each pixel to an xterm-256 color for a richer viewing experience.  
- **Subtitles**: Optionally display YouTube subtitles (`-sub`) if available.  
- **Frame Skipping**: Automatically skips frames to keep video and audio in sync if your system falls behind.

## Requirements

- **Python 3.7+** (tested on 3.9, 3.10, etc.)  
- **curses** (comes pre-installed on most Linux/Unix-like systems; for Windows, WSL is recommended)  
- **OpenCV** (`pip install opencv-python`)  
- **Pillow** (`pip install Pillow`)  
- **VLC Python bindings** (`pip install python-vlc`)  
- **YouTube-DL** (`pip install youtube-dl`)  
- **pytube** & **youtube_transcript_api** (`pip install pytube youtube-transcript-api`)

You’ll need **VLC** installed on your system so that `python-vlc` can call its libraries for audio playback.

## Installation

1. **Clone or Download** this repository.  
2. **Install Dependencies** using pip:
   ```
   pip install -r requirements.txt
   ```
   Or individually:
   ```
   pip install opencv-python Pillow python-vlc youtube_dl pytube youtube_transcript_api
   ```
3. **Ensure 256-Color Support**:  
   - On Linux, macOS, or WSL:  
     ```
     export TERM=xterm-256color
     ```
   - On Windows Terminal (via WSL), confirm by running:
     ```
     echo $TERM
     ```
     It should print `xterm-256color`.

## Usage

```
python ascii_video_player.py [options] <local_file>
OR
python ascii_video_player.py [options] -y <YouTubeURL>
```

### Options

- **`-y <link>`**  
  Download and play a YouTube video (requires `youtube_dl` and `pytube`).  
- **`-c`**  
  Use cached frames (skip extraction & resizing). Assumes you already have `frames/` and `resized/` folders populated.  
- **`-sub [lang]`**  
  Display YouTube subtitles (default or specified language).  
- **`-f <fps>`**  
  Limit ASCII rendering to `<fps>` frames per second, skipping frames as needed to keep in sync with audio.  
- **`-noskip`**  
  Don’t skip frames, even if we fall behind. The video may go out of sync with audio.  
- **`-debug`**  
  Show real-time FPS in the top-right corner of the terminal.  
- **`-color`**  
  Enable 256-color approximation. Without this flag, it defaults to grayscale.  
- **`-h` or `-help`**  
  Show usage info.

### Examples

1. **Play a local file with color**:
   ```
   python ascii_video_player.py -color myvideo.mp4
   ```
2. **Download and play a YouTube link, 10 FPS, with subtitles**:
   ```
   python ascii_video_player.py -y https://www.youtube.com/watch?v=XYZ -sub en -color -f 10
   ```

## Performance Tips

1. **Reduce Terminal Size**  
   A smaller width/height means fewer characters to draw, which can drastically improve speed.  
2. **Lower FPS**  
   Use `-f 10` or even `-f 5` to reduce how many frames get converted/drawn per second.  
3. **Skip Frames**  
   By default, if the script falls behind, it will skip frames to catch up (unless you use `-noskip`).  
4. **Disable 256-Color**  
   Color approximation is CPU-intensive, so if performance is too slow, omit `-color` to fall back to grayscale.  
5. **Efficient Environment**  
   Running under WSL2 on a modern CPU typically handles things better than older hardware or non-optimized environments.

## Contributing

Pull requests are NOT welcome. For major changes, please open an issue first to discuss potential modifications.


---

**Note:** 256-color ASCII rendering can be quite CPU-heavy, especially for higher-resolution videos or large terminal sizes. Adjust the above parameters to achieve smoother playback.