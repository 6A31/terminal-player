```markdown
# ASCII Video Player

This is a Python script that converts and displays video (local file or YouTube) in your terminal using ASCII characters. It supports optional color mode, subtitles (YouTube only), and adjustable framerates. Audio is played using [VLC](https://www.videolan.org/vlc/) via `python-vlc`.

## Features

- **Local File or YouTube**: Provide a local video file (`.mp4` etc.) or a YouTube link (downloads it locally).
- **ASCII Rendering**: Converts each frame to ASCII art, displayed in the terminal via `curses`.
- **Color Mode**: Approximate 8-color mode if your terminal supports colors.
- **Subtitles (YouTube only)**: Optionally fetch subtitles, with optional language code.
- **Adjustable FPS**: Reduce the ASCII framerate (audio still plays at normal speed).
- **Cached Frames**: Optionally skip extraction/resizing (faster subsequent runs).
- **Dynamic Skipping**: Skip frames if playback falls behind real-time (can be disabled).
- **Loading Indicators**: Displays a loading bar for frame extraction and resizing.
- **Debug Mode**: Display live FPS in the top-right corner.

## Requirements

- Python 3.x
- [pip](https://pip.pypa.io/en/stable/) for installing dependencies
- A terminal that supports [curses](https://docs.python.org/3/library/curses.html)
- [VLC](https://www.videolan.org/vlc/) installed on your system for audio playback

## Python Dependencies

Install the required Python libraries:

```bash
pip install opencv-python Pillow python-vlc youtube_dl pytube youtube_transcript_api
```

(Note: For `pytube`, you might also run `pip install pytube` separately if needed.)

## Usage

```bash
python ascii_video_player.py [options] <local_file> or -y <YouTubeLink>
```

### Options

- **`-y <link>`**: Play a YouTube video (downloads it first).
- **`-c`**: Use cached frames (skip extraction & resizing).
- **`-sub [lang]`**: Enable YouTube subtitles; optionally specify a [language code](https://support.google.com/youtube/answer/6140493).
- **`-f <fps>`**: Set a custom ASCII framerate (displays fewer frames per second). Audio still plays at normal speed (frames are skipped).
- **`-noskip`**: Disable dynamic skipping. If the program falls behind schedule, it won't skip frames (video may become out of sync with audio).
- **`-debug`**: Show live FPS (frames drawn per second) in the top-right of the terminal.
- **`-color`**: Enable color approximation (8-color ASCII).
- **`-h, -help`**: Display help and usage information, then exit.

### Examples

1. **Local file, normal run:**
    ```bash
    python ascii_video_player.py movie.mp4
    ```
2. **YouTube, with default subtitles, color, 10 FPS:**
    ```bash
    python ascii_video_player.py -y https://www.youtube.com/watch?v=XYZ -sub -color -f 10
    ```

## How It Works

1. **Frame Extraction**  
   - The script uses `OpenCV` (`cv2`) to read each frame of the video.  
   - Frames are saved as `frame0.jpg`, `frame1.jpg`, etc., in a `frames/` directory.

2. **Frame Resizing**  
   - Each frame is resized to match your terminal’s dimensions so it can be displayed neatly.  
   - Resized frames are saved in a `resized/` directory.

3. **ASCII Conversion**  
   - If **color** is disabled, each pixel's brightness is mapped to a character in the grayscale set.  
   - If **color** is **enabled**, the script picks both a character (based on brightness) and a color pair (one of 8 basic colors) that best approximates the original pixel.

4. **Playback**  
   - The script uses the `curses` library to draw the frames in the terminal.  
   - Audio playback is handled by **VLC**.  
   - The default framerate is the video’s native FPS, but you can adjust it with `-f <fps>`.  
   - **Dynamic Skipping** is on by default to stay in sync with the audio (disable with `-noskip`).

5. **YouTube Support**  
   - If `-y <link>` is used, the script uses [youtube_dl](https://github.com/ytdl-org/youtube-dl) to download the video in `.mp4` format.  
   - Subtitles are fetched via `youtube_transcript_api` if `-sub` is specified.

## Directories

- **`frames/`**: Temporary folder containing raw frames from the original video (extracted by OpenCV).  
- **`resized/`**: Temporary folder containing frames resized to your terminal’s width/height.

## Known Limitations

- **Terminal Size**: If you resize the terminal while the script is running, it won’t automatically adjust. Restart the script to adapt to the new terminal size.
- **Performance**: Large videos or high FPS can be CPU-intensive. Lower the FPS with `-f <fps>` if your machine struggles.
- **Subtitle Timing**: Subtitles are matched against approximate frame times. Some edge cases might not align perfectly.

## Contributing

Feel free to open issues or pull requests if you have fixes or improvements.

## License

This project is provided under the [MIT License](https://opensource.org/licenses/MIT).  
You are free to use, modify, and distribute this software as permitted.

---

**Enjoy ASCII playback!**  
If you find this project helpful or fun, a star on GitHub is appreciated. 
```