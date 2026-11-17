# MP3Gain 1.6.2

MP3Gain analyzes MP3 files and applies ReplayGain-based volume adjustments.
The Linux build produces the command-line application `mp3gain`.

## Linux build on Bazzite

Install the required dependency with Homebrew:

```sh
brew install mpg123
```

Build from the project directory:

```sh
make clean
make
```

The executable is created as `./mp3gain`. Verify the build with:

```sh
./mp3gain -v
./mp3gain -h
```

## Running

Analyze an MP3 file without changing it:

```sh
./mp3gain song.mp3
```

Apply the recommended track gain:

```sh
./mp3gain -r song.mp3
```

Apply the recommended album gain to multiple files:

```sh
./mp3gain -a album-track-01.mp3 album-track-02.mp3
```

Use `./mp3gain -h` for all command-line options.

## Graphical interface

The optional PySide6 GUI recursively loads MP3 files from a selected folder,
analyzes their current volume and clipping risk, and applies the requested
target volume:

```sh
python3 -m pip install PySide6
python3 mp3gain_gui.py
```

Enter the desired volume in dB (92 by default), select a folder, and click
**Analyze All**. Review the calculated gain for each track, then click
**Apply**. Each file is updated and analyzed again so the grid shows refreshed
values.

## Install

Install the executable system-wide:

```sh
sudo make install
```

By default this installs `mp3gain` into `/usr/local/bin`.

## Platform notes

The Unix/Linux command-line target is supported by the included Makefile.
The Visual Studio project files and `replaygaindll` target are Windows-specific
and are not built on Linux.
