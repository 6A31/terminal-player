# ASCII Video Player

This is a command-line Python application that plays back video (local or YouTube) in ASCII art directly in your terminal. It uses [VLC](https://www.videolan.org/vlc/), [OpenCV](https://opencv.org/), and [PIL (Pillow)](https://python-pillow.org/) to handle video extraction, conversion to ASCII, and audio playback.

## Features

- **Local Video Playback**: Supply a local file (e.g. `movie.mp4`).
- **YouTube Video Playback**: Supply a YouTube URL (`-y <URL>`); the video is downloaded temporarily.
- **Color or Grayscale ASCII**: Use `-color` to get each pixel approximated in 256-color.
- **Subtitles**: Automatically retrieve YouTube subtitles (`-sub` / `-sub <lang>`).
- **Frame Skipping**: Supply `-f <fps>` to decode fewer frames, reducing CPU load.
- **Dynamic Skipping**: Automatic skip of frames to maintain audio-video sync unless `-noskip` is specified.
- **Debug FPS**: A real-time FPS indicator in the top-right corner (`-debug`).
- **Caching**: Extract frames once (`-write`), then reuse them (`-c`) for faster subsequent playback.
  
## Requirements

- **Python 3.6+** (for f-strings, etc.)
- [**VLC**](https://www.videolan.org/vlc/) installed on your system (the `vlc` Python module relies on VLC).
- [**OpenCV**](https://pypi.org/project/opencv-python/) (`pip install opencv-python`).
- [**Pillow**](https://pypi.org/project/Pillow/) (`pip install pillow`).
- [**yt-dlp**](https://pypi.org/project/yt-dlp/) for YouTube downloading.
- [**pytube**](https://pypi.org/project/pytube/) (for some YouTube metadata extraction).
- [**youtube_transcript_api**](https://pypi.org/project/youtube-transcript-api/) (for subtitles).

## Installation

1. Install system packages (example below for Ubuntu/Debian):

   ```bash
   sudo apt-get update
   sudo apt-get install vlc libsm6 libxext6 libxrender-dev
   ```

2. Install Python dependencies:

   ```bash
   pip install opencv-python pillow yt-dlp pytube youtube_transcript_api python-vlc
   ```



## Usage

```
./ascii_video_player.py [options] <local_file> or -y <YouTubeLink>

Options:
  -y <link>    Play a YouTube video (downloads it first).
  -c           Use cached frames (skip extraction/resizing from disk).
               (Requires that you previously used -write so 'resized/' is populated
               with .png files and metadata.)
  -write       Store frames on disk in PNG format (lossless). This creates
               two loading bars: one for extraction, one for resizing.
               Without this, frames are handled purely in memory (one bar).
  -sub [lang]  Enable YouTube subtitles; optional language code.
  -f <fps>     Set a custom ASCII framerate (fewer frames per second).
               Audio still plays at normal speed (frames may be skipped).
  -noskip      Disable dynamic skipping (video may get out of sync).
  -debug       Show live FPS (frames drawn per second) top-right.
  -color       Enable color approximation (each pixel is a colored block).
  -h, -help    Show this help message and exit.
```

### Examples

1. **Play local file at default FPS**:
   ```
   ./ascii_video_player.py movie.mp4
   ```

2. **Download and play YouTube video in ASCII, with subtitles**:
   ```
   ./ascii_video_player.py -y https://www.youtube.com/watch?v=XYZ -sub en
   ```

3. **Write frames to disk for faster later playback**:
   ```
   ./ascii_video_player.py -write myvideo.mp4
   ```
   Then, to use those frames later:
   ```
   ./ascii_video_player.py -c
   ```

4. **Force ASCII playback at 10 FPS**:
   ```
   ./ascii_video_player.py movie.mp4 -f 10
   ```

## Notes

- **Caching**: When running with `-write`, the script writes frames in `frames/` and resized frames in `resized/`, plus a `resized/metadata.txt` for future verification (used by `-c`).
- **Frame Skipping**: If you provide `-f <fps>` and that FPS is lower than the source, only approximately `(Video_FPS / <fps>)` frames are decoded. This significantly reduces CPU usage for high-FPS sources.
- **Color Mode**: Using `-color` can slow down rendering because each pixel is drawn as a colored block. Grayscale ASCII is usually faster.
- **Subtitles**: Only works automatically for YouTube videos if subtitles are available. If no subtitles exist, no text will be displayed.

