# Open IPTV Player Test Kit v1

A channel-free test playlist for any IPTV or M3U player. Every entry is a synthetic test pattern made from scratch with ffmpeg (color patches, ramps, `testsrc2`, sine tones, synthesized speech, frame counters). There are no channels, no logos, no providers and no third-party video. Everything in this folder is dedicated to the public domain under CC0 1.0.

Load one address in your player:

```
https://nightmaretv.net/testkit.m3u
```

The list carries its own XMLTV guide in the header (`x-tvg-url="https://nightmaretv.net/testkit/epg.xml"`). Video is served as HLS from `https://builds.nightmaretv.net/testkit/v1/`.

## Player or provider?

The kit is hosted by us, not by your IPTV provider, so it separates the two questions:

* **TK01 does not play at all:** the problem is the player, the device or the network path (DNS, VPN, firewall). Your provider is not involved.
* **TK01 plays but one of your provider's channels does not:** the player and network can play a clean stream; look at the provider's stream (wrong codec, broken timestamps, expired account).
* **A kit vector with the same property also fails** (for example TK02 for HDR10 or TK05 for 5.1): the limit is in the player or device, and it will fail on any provider.

## Vectors

All clips are 20 s (TK08: 12 s, TK10: 30 s, TK11: 24 s). They are on-demand HLS: each entry ends, restart it to replay. Every frame shows the vector name, a frame number and a timestamp.

| Entry | What it tests | What you should see and hear | If it fails |
|---|---|---|---|
| TK01 SDR reference | 1080p25 H.264 High, BT.709, AAC stereo, TS segments | Moving `testsrc2` pattern, counter runs. A voice says "left" from the left speaker, then "right" from the right; short 1 kHz pip every second. | Nothing plays: player, device or network. Voices swapped: stereo channel order. |
| TK02 HDR10 PQ | 2160p25 HEVC Main 10, BT.2020, SMPTE ST 2084, mastering display P3 D65 1000 nit, MaxCLL 1000, MaxFALL 400, fMP4 segments | Gray steps from 0 to 10,000 nit; a PQ ramp; BT.709 and BT.2020 primaries side by side. On an HDR chain with tone mapping, 1000, 2000 and 4000 stay distinct. | Washed-out gray picture: HDR flags ignored, PQ shown as SDR. Steps above 1000 identical: hard clipping instead of tone mapping. No picture: no HEVC Main 10 or no 4K decode. |
| TK03 HLG | 1080p50 HEVC Main 10, BT.2020, ARIB STD-B67 (HLG), fMP4 | HLG signal steps 0 to 100 %; 75 % is reference white (about 203 nit). On SDR the picture still looks natural, only flatter. | Very dark or very contrasty: HLG treated as PQ or as plain BT.709 gamma. |
| TK04 10-bit gradient | 1080p25 HEVC Main 10, SDR BT.709 | A dark ramp with 64 fine steps above a copy rounded to 8 bit (16 wide bands). | The upper ramp looks like the lower one: somewhere the chain is 8-bit (decoder output, renderer or display). Dithering may hide steps; that is fine. |
| TK05 5.1 channel ID | AC-3 5.1 (FL FR FC LFE SL SR) at 448 kbit/s, H.264 video | A green box marks the speaker that should sound: front left, center, front right, surround right, surround left (voice), then LFE (40 Hz tone). | Voice from the wrong speaker: channel map error. Everything from the front: downmix to stereo. Silence: no AC-3 decode and no passthrough. |
| TK06 Audio and subtitle tracks | HLS master with two audio renditions (`eng`, `deu`) and two WebVTT subtitle renditions (English, Arabic) | Audio 1 says "audio track one" over 440 Hz; audio 2 says "audio track two" over 880 Hz. Subtitles change every 3 s; the Arabic track must render right to left; the last English cue has Turkish and German letters. | No track menu: alternate renditions not supported. Arabic letters reversed or disconnected: no RTL shaping. |
| TK07 A/V sync | 1080p50 H.264, AAC | A white flash and a beep at the same moment every second. A red marker sweeps a millisecond ruler and crosses 0 at the flash. When you hear the beep, read the marker: plus means audio is late. | Readings beyond about +125 ms or -45 ms (ITU-R BT.1359 detectability) need an audio delay setting, or the output device adds latency (Bluetooth, AVR processing). |
| TK08A-D Frame cadence | 23.976, 25, 50 and 59.94 fps, H.264 | A white bar moves 16 px every frame; ten boxes light one per frame. Motion must be even. | Regular jerks: frame rate and display refresh are not matched (for example 25 fps on a 60 Hz output). A long-exposure photo with gaps or doubled boxes shows dropped or repeated frames. |
| TK09 Interlaced | 1080i50, H.264 interlaced coding, top field first, flagged `tt` | Moving bars with clean edges and 50 motion steps per second. | Comb teeth on moving edges: no deinterlacing. Jerky but clean: deinterlacing at 25 frames instead of 50 fields. |
| TK10 Long GOP | H.264 with a keyframe only every 10 s; 2 s segments that mostly start without one | Seek to 0:05. The player should show a picture quickly (decoding from the previous keyframe) or wait for the next one. | Gray or green blocks for several seconds: the decoder was fed from the middle of a GOP. Long black screen: the player waits for a keyframe. |
| TK11 Discontinuity | `#EXT-X-DISCONTINUITY` twice: 1080p25 48 kHz, then 720p50 44.1 kHz with timestamps jumping by +1000 s, then back to 1080p25 with timestamps restarting | Three labelled parts play back to back without a freeze, black screen or lost audio. | Freeze or silence at a part boundary: the player does not reset timing or audio format at a discontinuity. This is common in live IPTV around ad breaks and source switches. |
| TK12 Missing stream | A URL that returns HTTP 404 on purpose | A clear error message, no endless spinner, and the rest of the list still works. | Endless loading or an app crash. |

## List parsing tests (`parse/`)

There is no formal specification for IPTV M3U attributes, so players differ. These small lists all point at TK01, so every entry that is parsed correctly also plays.

| File | What it tests |
|---|---|
| `p01-attributes.m3u` | `tvg-id`, `tvg-name`, empty `tvg-logo`, `tvg-chno`, `group-title`; upper-case attribute names; a duplicated attribute; an entry without attributes; duration `0` instead of `-1` |
| `p02-quotes-commas.m3u` | A comma inside a quoted attribute; a comma inside the title; `=` inside a value; unquoted and single-quoted attributes |
| `p03-utf8-rtl.m3u` | Arabic (right to left), Turkish dotted and dotless i, CJK, emoji, a name of almost 300 characters, an Arabic group name |
| `p04-bom-crlf.m3u` | UTF-8 byte order mark and Windows line endings, an empty line between entries |
| `p05-catchup-shift.m3u` | Header-level `tvg-shift`, `catchup` and `catchup-days`; per-channel overrides (`tvg-shift="0"`, `"-1.5"`, `catchup="append"` with `catchup-source`, `catchup="disabled"`) |
| `p06-extgrp-options.m3u` | `#EXTGRP`, `#EXTVLCOPT` and `#KODIPROP` lines between `#EXTINF` and the URL |
| `p07-large-2000.m3u` | 2,000 entries in 20 groups (load time and scrolling) |

## Guide test

Every programme in the guide is one hour long and its title states its own start time in UTC ("Should start 14:00 UTC"). If the 14:00 UTC programme does not sit at 14:00 UTC converted to your local time, the player or the list applies a wrong time zone or `tvg-shift`. With `p05-catchup-shift.m3u` the first entry should appear shifted by +2 hours and the third by -1.5 hours.

* Live guide (regenerated on every request, 6 hours back and 30 hours ahead): `https://nightmaretv.net/testkit/epg.xml`
* Static snapshot for offline use: `epg/testkit-epg-snapshot.xml` (3 days from the build date; rebuild with the script below).

## Same list, three names

`testkit.m3u`, `testkit-gh.m3u` and `testkit-llm.m3u` are byte-for-byte the same playlist apart from one comment line. They exist only so that request counts show where people found the kit (the site, this repository, AI assistants). No personal data is involved.

## Results with Nightmare TV's playback engine

Measured on 2026-11-19 with the Windows `libmpv-2.dll` that ships in Nightmare TV (mpv v0.41.0, sha256 `d3fa92bb...`), run headless (`vo=null`, `ao=null`, software decoding) over HTTP. This checks demuxing and decoding only. Picture output (HDR, deinterlacing, refresh-rate switching) and audio output (passthrough) depend on the device and settings and are not covered here. Raw data: `results/nightmare-tv-libmpv.json`.

| Entry | Result |
|---|---|
| TK01 | Plays to the end; 1920x1080, 25 fps, AAC stereo, 0 dropped frames |
| TK02 | Plays; HEVC 3840x2160 10-bit, primaries BT.2020, transfer PQ, MaxCLL 1000 read from the stream |
| TK03 | Plays; HEVC 10-bit, transfer HLG |
| TK04 | Plays; 10-bit output format (`yuv420p10`) |
| TK05 | Plays; AC-3 decoded as 5.1(side) |
| TK06 | Plays; both audio tracks (`eng`, `deu`) and both subtitle tracks (`en`, `ar`) listed and selectable; Arabic cue text delivered |
| TK07 | Plays; 50 fps |
| TK08A-D | Play; frame rate read as 23.976, 25, 50 and 59.94 |
| TK09 | Plays; frames flagged interlaced, top field first |
| TK10 | Plays; seek to 0:05 resumes playback |
| TK11 | Part A to part B works (1920x1080 to 1280x720). Headless, playback stalled at the part B start when the audio sample rate changed from 48 to 44.1 kHz; with `audio-samplerate=48000` all three parts played. Not yet confirmed with a real audio device. |
| TK12 | Load fails with an error, no hang |

List parsing with Nightmare TV's M3U parser (`lib/m3u.dart`, checked by `test/testkit_ayristirma_test.dart` in the app repository):

| File | Result |
|---|---|
| p01 | All 5 entries; upper-case attribute names read; for a duplicated attribute the last one wins |
| p02 | Commas inside quoted attributes handled. A comma inside the title cuts it (the title is taken after the last comma). Unquoted and single-quoted attributes are ignored. |
| p03 | All names and the Arabic group intact |
| p04 | BOM and CRLF handled |
| p05 | Header `tvg-shift` +2 h inherited, channel values 0 and -1.5 h override it; catchup days 3 and 7; `disabled` turns catchup off |
| p06 | `#EXTGRP` used as group fallback; `#EXTVLCOPT` and `#KODIPROP` lines are not treated as URLs |
| p07 | 2,000 entries |

If you run the kit in another player, the result is yours to publish; we do not publish other players' results.

## Rebuild

Everything here is reproducible with ffmpeg 6 or later (with libx264, libx265, libflite and drawtext) and Python 3.10+, no other packages:

```
python tools/testkit/uret.py medya      # 12 vectors as HLS, about 42 MB
python tools/testkit/uret.py listeler   # playlists, parse lists, guide snapshot
python tools/testkit/uret.py dogrula    # ffprobe checks -> results/ffprobe.json
python tools/testkit/mpv_dogrula.py --dll <path to libmpv-2.dll>
```

On-screen text is rendered with Roboto Condensed (Apache License 2.0). The font file is not part of the kit. Speech is synthesized with Flite through ffmpeg.

## License

The test vectors, playlists, guide files and this README are dedicated to the public domain under [CC0 1.0 Universal](LICENSE). You may copy, modify and redistribute them, including in bug reports and commercial products, without asking and without attribution.

## Regenerate the media

The video files are not stored in this repository; they are served from `https://builds.nightmaretv.net/testkit/v1/`. `tools/testkit/uret.py` rebuilds every vector from scratch with ffmpeg. It expects the Roboto Condensed Bold font (download it from Google Fonts) at `assets/fonts/RobotoCondensed-Bold.ttf` in this repository (not included; adjust `YAZI_TIPI` in the script if you keep it elsewhere). Code comments are in Turkish.

## Maintainer

Made by the developer of [Nightmare TV](https://nightmaretv.net). Issues and pull requests with new test vectors are welcome.
