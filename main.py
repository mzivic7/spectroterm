import argparse
import curses
import signal
import sys
import time

import numpy as np
import soundcard as sc


def log_band_volumes(data, sample_rate, num_bands, min_freq, max_freq, max_ref):
    """Get logarythmic volume in dB for specified number of bands, from sound sample, with interpolation between bands"""
    # get magnitude from fft
    raw_magnitude = np.abs(np.fft.rfft(data))
    freqs = np.fft.rfftfreq(len(data), 1 / sample_rate)

    # split into logarithmic bands
    band_edges = np.logspace(np.log10(min_freq), np.log10(max_freq), num_bands + 1)
    magnitue = np.zeros(num_bands)
    for i in range(num_bands):
        left = band_edges[i]
        right = band_edges[i+1]
        idx = np.where((freqs >= left) & (freqs < right))[0]

        # interpolate between bands
        if len(idx) == 0:
            left_bin = np.searchsorted(freqs, left)
            right_bin = np.searchsorted(freqs, right)
            bins = []
            if left_bin > 0:
                bins.append(left_bin - 1)
            if left_bin < len(freqs):
                bins.append(left_bin)
            if right_bin > 0 and right_bin != left_bin:
                bins.append(right_bin - 1)
            if right_bin < len(freqs) and right_bin != left_bin:
                bins.append(right_bin)
            bins = list(set(bins))
            weights = []
            for b in bins:
                center = freqs[b]
                band_center = (left + right) / 2
                d = abs(center - band_center) + 1e-6
                weights.append(1/d)
            weights = np.array(weights)
            weights /= np.sum(weights)
            magnitue[i] = np.sqrt(np.sum((raw_magnitude[bins]**2) * weights))   # weighted RMS
        else:
            magnitue[i] = np.sqrt(np.mean(raw_magnitude[idx]**2))   # RMS

    # magnitue to negative dB
    db = 20 * np.log10(magnitue / max_ref + 1e-12)    # add small value to avoid log(0)
    return np.maximum(db, -90)


def draw_log_x_axis(screen, num_bars, x, h, min_freq, max_freq, have_box=True):
    """Draw logarythmic Hz x axis"""
    freqs = [30, 100, 200, 500, 1000, 2000, 5000, 10000, 16000]
    band_edges = np.logspace(np.log10(min_freq), np.log10(max_freq), num_bars + 1)
    for freq in freqs:
        if band_edges[0] < freq < band_edges[-1]:
            pos = np.argmin(np.abs(band_edges - freq))
            if 0 <= pos < num_bars:
                if freq >= 1000:
                    label = f"{round(freq/1000)}k"
                else:
                    label = str(round(freq))
                if pos < num_bars - 5:
                    screen.addstr(h - 1 - have_box, x + pos, label)
        screen.addstr(h - 1 - have_box, x + num_bars - 3 + have_box * 2, "Hz")


def draw_log_y_axis(screen, bar_height, min_db, max_db, have_box=True):
    """Draw logarythmic dB y axis"""
    levels = list(range(int(min_db), int(max_db) + 1, 10))
    for db in levels:
        # get y coordinate
        pos = int(np.interp(db, (min_db, max_db), (bar_height, 0)))
        label = str(db).rjust(3)
        if 0 <= pos < bar_height:
            screen.addstr(have_box + pos, have_box, label)
    screen.addstr(have_box, have_box + 1, "dB")


def get_color(y, bar_height, use_color):
    """Get color id by bar height"""
    if not use_color:
        return curses.color_pair(0)
    relative = (bar_height - y) / bar_height
    if relative < 0.5:
        return curses.color_pair(1)   # green
    if relative < 0.75:
        return curses.color_pair(2)   # yellow
    return curses.color_pair(3)   # red


def draw_ui(screen, draw_box, draw_axes, min_freq, max_freq, min_db, max_db):
    """Draw UI"""
    h, w = screen.getmaxyx()
    spectrum_hwyx = (
        h - draw_box - draw_axes,
        w - 2 * draw_box - 4 * draw_axes,
        draw_box,
        draw_box + 4 * draw_axes,
    )
    spectrum_win = screen.derwin(*spectrum_hwyx)
    bar_height, num_bars = spectrum_win.getmaxyx()
    if draw_box:
        screen.box()
        screen.addstr(0, 2, "Spectrum Analyzer")
    if draw_axes:
        draw_log_y_axis(screen, bar_height, min_db, max_db, draw_box)
        draw_log_x_axis(screen, num_bars, 4, h, min_freq, max_freq, draw_box)
    return spectrum_win


def main(screen, args):
    """Main app function"""
    curses.curs_set(0)
    screen.nodelay(True)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(0, -1, -1)
    curses.init_pair(1, 46, -1)
    curses.init_pair(2, 214, -1)
    curses.init_pair(3, 196, -1)

    # load config
    color = args.color
    box = args.box
    axes = args.axes
    peaks = args.peaks
    fall_speed = args.fall_speed
    bar_character = args.bar_character[0]
    peak_character = args.peak_character[0]
    sample_rate = args.sample_rate
    sample_size = args.sample_size / 1000
    reference_max = args.reference_max
    peak_hold = args.peak_hold / 1000
    min_freq = args.min_freq
    max_freq = args.max_freq
    min_db = args.min_db
    max_db = args.max_db

    prev_bar_heights = None
    prev_update_time = time.perf_counter()
    peak_heights = []

    # get loopback device
    default_speaker = sc.default_speaker()
    loopback_mic = sc.get_microphone(default_speaker.name, include_loopback=True)

    try:
        with loopback_mic.recorder(samplerate=sample_rate, channels=1, blocksize=int(sample_rate * sample_size)) as rec:
            h, w = screen.getmaxyx()
            spectrum_win = draw_ui(screen, box, axes, min_freq, max_freq, min_db, max_db)
            bar_height, num_bars = spectrum_win.getmaxyx()
            while True:
                # handle input
                key = screen.getch()
                if key == 113:
                    break
                elif key == curses.KEY_RESIZE:
                    h, w = screen.getmaxyx()
                    spectrum_win = draw_ui(screen, box, axes, min_freq, max_freq, min_db, max_db)
                    bar_height, num_bars = spectrum_win.getmaxyx()

                # get and process data
                data = rec.record(numframes=int(sample_rate * sample_size)).flatten()
                volume_db = log_band_volumes(data, sample_rate, num_bars, min_freq, max_freq, reference_max)

                # calculate heights on screen
                raw_bar_heights = np.clip(np.round(np.interp(volume_db, (min_db, max_db), (0, bar_height))).astype(int), 0, bar_height)

                # falling bars
                now = time.perf_counter()
                dt = now - prev_update_time
                prev_update_time = now
                if prev_bar_heights is None or len(prev_bar_heights) != len(raw_bar_heights):
                    prev_bar_heights = raw_bar_heights.copy()
                else:
                    max_fall = int(fall_speed * dt)
                    for i in range(len(raw_bar_heights)):
                        if raw_bar_heights[i] >= prev_bar_heights[i]:
                            prev_bar_heights[i] = raw_bar_heights[i]
                        else:
                            prev_bar_heights[i] = max(raw_bar_heights[i], prev_bar_heights[i] - max_fall)
                bar_heights = prev_bar_heights

                # peak marker
                if peaks:
                    if len(peak_heights) != len(bar_heights):
                        peak_heights = bar_heights.copy()
                        peak_times = [now] * len(bar_heights)
                    for i, bh in enumerate(bar_heights):
                        if bh > peak_heights[i]:
                            peak_heights[i] = bh
                            peak_times[i] = now
                        elif now - peak_times[i] > peak_hold:
                            peak_heights[i] = bh
                            peak_times[i] = now

                # draw spectrum
                for y in range(bar_height-1):
                    line = []
                    for bar in bar_heights:
                        if y >= bar_height - bar:
                            line.append(bar_character)
                        else:
                            line.append(" ")
                    if peaks:
                        for x, peak in enumerate(peak_heights):
                            if y == bar_height - peak:
                                line[x] = peak_character
                    spectrum_win.insstr(y, 0, "".join(line), get_color(y, bar_height, color))
                    spectrum_win.refresh()


    except Exception as e:
        screen.clear()
        screen.addstr(0, 0, f"Error: {e}")
        screen.refresh()
        time.sleep(2)


def sigint_handler(signum, frame):   # noqa
    """Handle Ctrl-C event"""
    sys.exit()


def argparser():
    """Setup argument parser for CLI"""
    parser = argparse.ArgumentParser(
        prog="spectroterm",
        description="Curses based spectrometer for currently playing audio",
    )
    parser._positionals.title = "arguments"
    parser.add_argument(
        "-a",
        "--axes",
        action="store_true",
        help="draw graph axes",
    )
    parser.add_argument(
        "-b",
        "--box",
        action="store_true",
        help="draw lines at terminal borders",
    )
    parser.add_argument(
        "-c",
        "--color",
        action="store_true",
        help="3 color mode",
    )
    parser.add_argument(
        "-p",
        "--peaks",
        action="store_true",
        help="draw peaks that disappear after some time",
    )
    parser.add_argument(
        "-f",
        "--fall-speed",
        type=int,
        default=40,
        help="speed at which bars fall in characters per second",
    )
    parser.add_argument(
        "-o",
        "--peak-hold",
        type=int,
        default=2000,
        help="time after which peak will dissapear, in ms",
    )
    parser.add_argument(
        "-r",
        "--bar-character",
        type=str,
        default="█",
        help="character used to draw bars",
    )
    parser.add_argument(
        "-k",
        "--peak_character",
        type=str,
        default="_",
        help="character used to draw peaks",
    )
    parser.add_argument(
        "--min-freq",
        type=int,
        default=30,
        help="minimum frequency on spectrum graph (x-axis)",
    )
    parser.add_argument(
        "--max-freq",
        type=int,
        default=16000,
        help="maximum frequency on spectrum graph (x-axis)",
    )
    parser.add_argument(
        "--min-db",
        type=int,
        default=-90,
        help="minimum loudness on spectrum graph (y-axis)",
    )
    parser.add_argument(
        "--max-db",
        type=int,
        default=0,
        help="maximum loudness on spectrum graph (y-axis)",
    )

    parser.add_argument(
        "--sample-rate",
        type=int,
        default=44100,
        help="loopback device sample rate",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=50,
        help="sample size in ms, higher values will decrease fps",
    )
    parser.add_argument(
        "--reference-max",
        type=int,
        default=3000,
        help="Value used to tune maximum loudness of sound",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = argparser()
    signal.signal(signal.SIGINT, sigint_handler)
    curses.wrapper(main, args)
