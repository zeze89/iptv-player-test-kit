#!/usr/bin/env python3
"""Open IPTV Player Test Kit: vektor ureticisi (yalniz ffmpeg + Python stdlib).

NEDEN (2026-11-19, SEO+GEO yarismasi 2. tur, aday U): kanal icermeyen, her
oynaticiya yuklenebilen, CC0 bir test kiti. Butun goruntu ve ses SIFIRDAN
sentetik uretilir (renk alanlari, testsrc2, sinus tonlari, flite konusma
sentezi, sayaclar). Ucuncu taraf film ya da klip YOK, bu yuzden ciktinin
tamami CC0 1.0 ile yayinlanabilir. Tek dis girdi depodaki yazi tipi
`assets/fonts/RobotoCondensed-Bold.ttf` (Apache 2.0); ekrana basilan glif
yazi tipinin kopyasi degildir.

KULLANIM
    python tools/testkit/uret.py medya    [--cikti testkit/media/v1] [--is-dizini <gecici>]
    python tools/testkit/uret.py listeler [--taban https://builds.nightmaretv.net/testkit/v1]
    python tools/testkit/uret.py dogrula  [--cikti testkit/media/v1]

`medya`   12 vektoru HLS olarak uretir (her biri kendi klasorunde index.m3u8).
`listeler` testkit/ ve site/ altindaki .m3u listelerini, ayristirma
          listelerini ve statik XMLTV yedegini yazar (ayni kaynaktan, ayrisamaz).
`dogrula` her vektoru ffprobe ile denetler, testkit/results/ffprobe.json yazar;
          beklenen deger tutmazsa cikis kodu 1.

Gereken: ffmpeg/ffprobe 6+ (libx264, libx265, libflite, drawtext). Gelistirmede
kullanilan: gyan.dev 8.1 full build.
"""
from __future__ import annotations

import argparse
import array
import datetime as dt
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KOK = Path(__file__).resolve().parents[2]
KIT = KOK / "testkit"
SITE = KOK / "site"
YAZI_TIPI = KOK / "assets" / "fonts" / "RobotoCondensed-Bold.ttf"

# R2 genel adresi. Kova `nightmare-test-builds`, ozel alan adi
# builds.nightmaretv.net (2026-10-24'ten beri bagli). Kit `testkit/v1/` onekinde.
# Ayri kova ya da alt alan secilirse YALNIZ bu satir degisir.
VARSAYILAN_TABAN = "https://builds.nightmaretv.net/testkit/v1"
EPG_DINAMIK = "https://nightmaretv.net/testkit/epg.xml"
KIT_ADI = "Open IPTV Player Test Kit v1"
# Ana depo GIZLI; beklenen sonuc tablosu sitede (mevcut sayfa) ve acilacak
# ayri acik depoda durur. Liste icindeki adres yalniz canli olani gostersin.
BEKLENEN_SONUC_URL = "https://nightmaretv.net/iptv-player-benchmark-2026#test-kit"

SURE = 20  # saniye; cogu vektor


# --------------------------------------------------------------------------
# Vektor tablosu: listeler, README ve dogrulama ayni tablodan beslenir.
# --------------------------------------------------------------------------
VEKTORLER = [
    dict(no="01", klasor="01-sdr-reference", ad="TK01 SDR reference 1080p25 H.264 stereo",
         grup="Test Kit: baseline"),
    dict(no="02", klasor="02-hdr10-pq-2160p", ad="TK02 HDR10 PQ 2160p25 HEVC Main10",
         grup="Test Kit: HDR"),
    dict(no="03", klasor="03-hlg-1080p50", ad="TK03 HLG 1080p50 HEVC Main10",
         grup="Test Kit: HDR"),
    dict(no="04", klasor="04-10bit-gradient", ad="TK04 10-bit gradient SDR HEVC Main10",
         grup="Test Kit: picture"),
    dict(no="05", klasor="05-ac3-5.1-channel-id", ad="TK05 5.1 channel identification AC-3",
         grup="Test Kit: audio"),
    dict(no="06", klasor="06-multi-audio-subtitles", ad="TK06 Two audio tracks and two subtitle tracks",
         grup="Test Kit: audio"),
    dict(no="07", klasor="07-av-sync-1080p50", ad="TK07 Audio video sync flash and beep 1080p50",
         grup="Test Kit: timing"),
    dict(no="08a", klasor="08a-cadence-23.976", ad="TK08A Frame cadence 23.976 fps",
         grup="Test Kit: timing"),
    dict(no="08b", klasor="08b-cadence-25", ad="TK08B Frame cadence 25 fps",
         grup="Test Kit: timing"),
    dict(no="08c", klasor="08c-cadence-50", ad="TK08C Frame cadence 50 fps",
         grup="Test Kit: timing"),
    dict(no="08d", klasor="08d-cadence-59.94", ad="TK08D Frame cadence 59.94 fps",
         grup="Test Kit: timing"),
    dict(no="09", klasor="09-interlaced-1080i50", ad="TK09 Interlaced 1080i50 top field first",
         grup="Test Kit: picture"),
    dict(no="10", klasor="10-long-gop", ad="TK10 Long GOP 10 s, segments not on keyframes",
         grup="Test Kit: stream"),
    dict(no="11", klasor="11-discontinuity", ad="TK11 Discontinuity and resolution change",
         grup="Test Kit: stream"),
    dict(no="12", klasor="12-missing-stream", ad="TK12 Missing stream (HTTP 404 on purpose)",
         grup="Test Kit: stream"),
]


def tvg_id(v: dict) -> str:
    return f"tk{v['no']}.testkit"


# --------------------------------------------------------------------------
# Yardimcilar
# --------------------------------------------------------------------------

def calistir(args: list[str], cwd: Path | None = None) -> None:
    print("  $", " ".join(str(a) for a in args[:12]), "..." if len(args) > 12 else "")
    r = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-4000:])
        raise SystemExit(f"komut basarisiz: {args[0]}")


FF = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]


def yazi(metin: str, x: str, y: str, boy: int = 40, renk: str = "white",
         kutu: bool = True) -> str:
    """drawtext parcasi. Yazi tipi is dizininde `font.ttf` (cwd), Windows'ta
    surucu harfli yolun filtre kacisi derdi olmasin diye."""
    t = (metin.replace("\\", "\\\\").replace("'", "’").replace(":", "\\:")
         .replace("%", "\\%"))
    s = f"drawtext=fontfile=font.ttf:text='{t}':x={x}:y={y}:fontsize={boy}:fontcolor={renk}"
    if kutu:
        s += ":box=1:boxcolor=black@0.6:boxborderw=8"
    return s


def sayac(x: str = "w-tw-40", y: str = "40", boy: int = 44, renk: str = "white") -> str:
    """Kare numarasi ve zaman: gecen her kare ekranda okunur."""
    return (f"drawtext=fontfile=font.ttf:text='frame %{{n}}  t=%{{pts\\:hms}}':x={x}:y={y}"
            f":fontsize={boy}:fontcolor={renk}:box=1:boxcolor=black@0.6:boxborderw=8")


def baslik(v: dict, renk: str = "white", boy: int = 44) -> list[str]:
    return [yazi(f"{KIT_ADI} · {v['ad']}", "40", "40", boy, renk),
            yazi("CC0 · nightmaretv.net/testkit · synthetic pattern, no channel content",
                 "40", "h-80", int(boy * 0.7), renk)]


_KAYAN = [0]


def kayan(renk: str, gen: int, yuk: int, x: str, y: str, enable: str | None = None) -> str:
    """Kareden kareye yer degistiren dolu kutu. drawbox x/y ifadesini yalniz
    yapilandirmada hesapliyor (olculdu: isaretci hep ayni yerde kaldi); bu
    yuzden renk kaynagi + overlay (eval=frame). Virgulle birlestirilen -vf
    zincirine dogrudan girer."""
    _KAYAN[0] += 1
    k = _KAYAN[0]
    en = f":enable='{enable}'" if enable else ""
    return (f"null[kz{k}];color=c={renk}:s={gen}x{yuk}[km{k}];"
            f"[kz{k}][km{k}]overlay=x='{x}':y={y}:eval=frame:shortest=1{en}[ko{k}];[ko{k}]null")


def flite(metin: str, hedef: Path) -> None:
    calistir(FF + ["-f", "lavfi", "-i", f"flite=text='{metin}':voice=slt",
                   "-af", "aresample=48000,volume=2.0", "-ac", "1", str(hedef)])


def HLS_TS(hedef: Path) -> list[str]:
    h = hedef.as_posix()
    return ["-f", "hls", "-hls_time", "4", "-hls_playlist_type", "vod",
            "-hls_segment_filename", f"{h}/seg_%03d.ts", f"{h}/index.m3u8"]


def HLS_FMP4(hedef: Path) -> list[str]:
    # Yol ileri egik cizgili olmali: ters egik cizgili Windows yolunda ffmpeg
    # init.mp4'u liste klasorune degil calisma dizinine yaziyor (olculdu).
    h = hedef.as_posix()
    return ["-f", "hls", "-hls_time", "4", "-hls_playlist_type", "vod",
            "-hls_segment_type", "fmp4", "-hls_fmp4_init_filename", "init.mp4",
            "-hls_segment_filename", f"{h}/seg_%03d.m4s", f"{h}/index.m3u8"]


BT709 = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
         "-color_range", "tv"]


def x264(gop: int, ek: str = "") -> list[str]:
    # VUI renk etiketleri x264'e ACIKCA verilir: ffmpeg 8'de -color_trc vb.
    # cikti secenekleri filtre zincirinden gelen "unknown" kare ozelligine
    # yeniliyor ve TS'de etiket bos cikiyordu (ffprobe ile olculdu).
    p = (f"keyint={gop}:min-keyint={gop}:scenecut=0:colorprim=bt709:transfer=bt709:colormatrix=bt709"
         + (":" + ek if ek else ""))
    # Tavan 2,5 Mbit/sn: testsrc2'nin gurultulu alanlari aksi halde 8 Mbit/sn
    # yiyor (olculdu); IPTV'de 1080p H.264 icin de gercekci bir oran.
    return ["-c:v", "libx264", "-preset", "slow", "-crf", "20", "-maxrate", "2500k", "-bufsize", "5000k",
            "-profile:v", "high",
            "-pix_fmt", "yuv420p", "-x264-params", p]


def aac(kanal: int = 2) -> list[str]:
    return ["-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", str(kanal)]


# --------------------------------------------------------------------------
# PQ / HLG / renk matematigi (ST 2084, BT.2100, BT.2020 NCL)
# --------------------------------------------------------------------------
M1, M2 = 2610 / 16384, 2523 / 4096 * 128
C1, C2, C3 = 3424 / 4096, 2413 / 4096 * 32, 2392 / 4096 * 32


def pq(nit: float) -> float:
    y = max(nit, 0.0) / 10000.0
    yp = y ** M1
    return ((C1 + C2 * yp) / (1 + C3 * yp)) ** M2


def pq_ters(e: float) -> float:
    ep = e ** (1 / M2)
    return 10000.0 * (max(ep - C1, 0) / (C2 - C3 * ep)) ** (1 / M1)


def ycc2020(r: float, g: float, b: float) -> tuple[int, int, int]:
    """Dogrusal olmayan R'G'B' (0-1) -> 10 bit dar aralik Y'CbCr (BT.2020 NCL)."""
    y = 0.2627 * r + 0.6780 * g + 0.0593 * b
    cb = (b - y) / 1.8814
    cr = (r - y) / 1.4746
    return (round(64 + 876 * y), round(512 + 896 * cb), round(512 + 896 * cr))


def ycc709(r: float, g: float, b: float) -> tuple[int, int, int]:
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    cb = (b - y) / 1.8556
    cr = (r - y) / 1.5748
    return (round(64 + 876 * y), round(512 + 896 * cb), round(512 + 896 * cr))


# BT.709 -> BT.2020 dogrusal RGB (ITU-R BT.2087)
M709_2020 = [[0.6274, 0.3293, 0.0433], [0.0691, 0.9195, 0.0114], [0.0164, 0.0880, 0.8956]]


def carp(m, v):
    return [sum(m[i][j] * v[j] for j in range(3)) for i in range(3)]


HLG_A, HLG_B, HLG_C = 0.17883277, 1 - 4 * 0.17883277, 0.5 - 0.17883277 * math.log(4 * 0.17883277)


def hlg_oetf(e: float) -> float:
    return math.sqrt(3 * e) if e <= 1 / 12 else HLG_A * math.log(12 * e - HLG_B) + HLG_C


# --------------------------------------------------------------------------
# Ham 10 bit kare: her satir bir "bant" tanimindan; bant icinde satirlar ayni
# oldugu icin satir bir kez kurulur ve tekrarlanir (stdlib ile hizli).
# --------------------------------------------------------------------------

class Kare:
    def __init__(self, w: int, h: int, zemin=(64, 512, 512)):
        self.w, self.h = w, h
        self.y = [None] * h
        self.u = [None] * (h // 2)
        self.v = [None] * (h // 2)
        self.zemin = zemin

    def bant(self, y0: int, y1: int, piksel):
        """piksel(x) -> (Y, Cb, Cr) 10 bit. [y0, y1) cift olmali."""
        ys = array.array("H", (piksel(x)[0] for x in range(self.w)))
        us = array.array("H", (piksel(x)[1] for x in range(0, self.w, 2)))
        vs = array.array("H", (piksel(x)[2] for x in range(0, self.w, 2)))
        for r in range(y0, y1):
            self.y[r] = ys
        for r in range(y0 // 2, y1 // 2):
            self.u[r] = us
            self.v[r] = vs

    def yaz(self, yol: Path):
        zy = array.array("H", [self.zemin[0]] * self.w)
        zu = array.array("H", [self.zemin[1]] * (self.w // 2))
        zv = array.array("H", [self.zemin[2]] * (self.w // 2))
        with open(yol, "wb") as f:
            for r in self.y:
                f.write((r or zy).tobytes())
            for r in self.u:
                f.write((r or zu).tobytes())
            for r in self.v:
                f.write((r or zv).tobytes())


def yamalar(degerler, w: int):
    """Esit genislikte yamalar: degerler[i] = (Y, Cb, Cr)."""
    n = len(degerler)
    return lambda x: degerler[min(x * n // w, n - 1)]


# --------------------------------------------------------------------------
# Vektorler
# --------------------------------------------------------------------------

def v01(is_: Path, hedef: Path, v: dict):
    flite("left", is_ / "sol.wav")
    flite("right", is_ / "sag.wav")
    # 4 sn dongu: 0 sn "left" yalniz sol, 2 sn "right" yalniz sag, her saniye
    # basinda 100 ms 1 kHz pip iki kanalda (-20 dBFS).
    fc = (
        "[1:a]apad=whole_dur=4,aloop=loop=-1:size=192000,atrim=0:20[l];"
        "[2:a]adelay=2000,apad=whole_dur=4,aloop=loop=-1:size=192000,atrim=0:20[r];"
        "aevalsrc='0.1*sin(2*PI*1000*t)*lt(mod(t,1),0.1)':s=48000:d=20[p];"
        "[p]asplit[p1][p2];[l][p1]amix=inputs=2:normalize=0[lm];[r][p2]amix=inputs=2:normalize=0[rm];"
        "[lm][rm]join=inputs=2:channel_layout=stereo[a]"
    )
    vf = ",".join(["format=yuv420p"] + baslik(v) + [sayac(y="120"),
                  yazi("Audio: voice says left then right, 1 kHz pip each second", "40", "h-160", 32)])
    calistir(FF + ["-f", "lavfi", "-i", f"testsrc2=s=1920x1080:r=25:d={SURE}",
                   "-i", "sol.wav", "-i", "sag.wav",
                   "-filter_complex", fc + f";[0:v]{vf}[v]", "-map", "[v]", "-map", "[a]",
                   *x264(50), *BT709, *aac(), "-t", str(SURE), *HLS_TS(hedef)], cwd=is_)


def v02(is_: Path, hedef: Path, v: dict):
    w, h = 3840, 2160
    k = Kare(w, h, ycc2020(0, 0, 0))
    nits = [0, 0.1, 1, 10, 100, 203, 400, 1000, 2000, 4000, 10000]
    k.bant(240, 760, yamalar([ycc2020(pq(n), pq(n), pq(n)) for n in nits], w))
    # Surekli PQ rampasi: kod degeri x ile dogrusal, 0 -> 10.000 nit.
    k.bant(960, 1240, lambda x: ycc2020(x / (w - 1), x / (w - 1), x / (w - 1)))
    renkler = []
    for lin in ([1, 0, 0], [0, 1, 0], [0, 0, 1]):
        renkler.append([pq(100 * c) for c in carp(M709_2020, lin)])  # BT.709 primer, 100 nit
    for lin in ([1, 0, 0], [0, 1, 0], [0, 0, 1]):
        renkler.append([pq(100 * c) for c in lin])  # BT.2020 primer, 100 nit
    k.bant(1440, 1840, yamalar([ycc2020(*c) for c in renkler], w))
    k.yaz(is_ / "kare.yuv")
    # Etiket rengi ~200 nit gri (PQ ~0.58): yazi 10.000 nit beyaz olmasin.
    g = "0x939393"
    etiket = []
    for i, n in enumerate(nits):
        etiket.append(yazi(f"{n:g} nit", str(int((i + 0.5) * w / len(nits)) - 70), "780", 44, g, False))
    for n in (100, 203, 1000, 4000, 10000):
        x = int(pq(n) * (w - 1))
        etiket.append(yazi(f"| {n} nit", str(x), "1250", 40, g, False))
    for i, s in enumerate(["BT.709 red", "BT.709 green", "BT.709 blue",
                           "BT.2020 red", "BT.2020 green", "BT.2020 blue"]):
        etiket.append(yazi(s, str(int((i + 0.5) * w / 6) - 110), "1860", 44, g, False))
    etiket.append(yazi("PQ steps: 1000, 2000, 4000 and 10000 should stay distinct on a tone-mapping player. "
                       "Equal patches = clipping.", "40", "880", 40, g, False))
    etiket.append(yazi("PQ ramp: where it goes flat is where the chain clips.", "40", "1300", 40, g, False))
    etiket.append(yazi("Lower row: BT.2020 patches must look more saturated than BT.709 on a wide-gamut chain.",
                       "40", "1920", 40, g, False))
    hareket = kayan(g, 120, 60, f"mod(t*400,{w}-120)", "2010")
    vf = ",".join(baslik(v, g) + etiket + [hareket, sayac(y="120", renk=g), "format=yuv420p10le"])
    x265 = ("keyint=50:min-keyint=50:scenecut=0:repeat-headers=1:hdr10=1:hdr10-opt=1"
            ":colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:range=limited"
            ":master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1)"
            ":max-cll=1000,400:log-level=error")
    calistir(FF + ["-f", "rawvideo", "-pix_fmt", "yuv420p10le", "-s", f"{w}x{h}", "-framerate", "25",
                   "-stream_loop", "-1", "-i", "kare.yuv",
                   "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo",
                   "-vf", vf, "-t", str(SURE),
                   "-c:v", "libx265", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p10le",
                   "-profile:v", "main10", "-tag:v", "hvc1", "-x265-params", x265,
                   "-colorspace", "bt2020nc", "-color_primaries", "bt2020", "-color_trc", "smpte2084",
                   "-color_range", "tv", *aac(), *HLS_FMP4(hedef)], cwd=is_)


def v03(is_: Path, hedef: Path, v: dict):
    w, h = 1920, 1080
    k = Kare(w, h, ycc2020(0, 0, 0))
    seviye = [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0]  # HLG sinyal seviyesi
    k.bant(140, 400, yamalar([ycc2020(s, s, s) for s in seviye], w))
    k.bant(500, 640, lambda x: ycc2020(x / (w - 1), x / (w - 1), x / (w - 1)))
    renkler = []
    # Sahne isigi 0.26 (yaklasik 75 % HLG sinyali, ref. beyaz 203 nit civari)
    for lin in ([1, 0, 0], [0, 1, 0], [0, 0, 1]):
        renkler.append([hlg_oetf(0.26 * c) for c in carp(M709_2020, lin)])
    for lin in ([1, 0, 0], [0, 1, 0], [0, 0, 1]):
        renkler.append([hlg_oetf(0.26 * c) for c in lin])
    k.bant(740, 940, yamalar([ycc2020(*c) for c in renkler], w))
    k.yaz(is_ / "kare.yuv")
    g = "0xb4b4b4"  # ~75 % HLG: referans beyaz civari
    etiket = [yazi(f"{int(s * 100)} %", str(int((i + 0.5) * w / len(seviye)) - 30), "410", 28, g, False)
              for i, s in enumerate(seviye)]
    etiket.append(yazi("HLG signal steps. 75 % is reference white (about 203 nit). "
                       "SDR fallback: picture looks natural but flatter.", "30", "450", 26, g, False))
    etiket.append(yazi("HLG ramp 0-100 %", "30", "650", 26, g, False))
    for i, s in enumerate(["709 R", "709 G", "709 B", "2020 R", "2020 G", "2020 B"]):
        etiket.append(yazi(s, str(int((i + 0.5) * w / 6) - 40), "950", 28, g, False))
    hareket = kayan(g, 60, 30, f"mod(t*300,{w}-60)", "1000")
    vf = ",".join(baslik(v, g, 30) + etiket + [hareket, sayac(y="90", boy=30, renk=g), "format=yuv420p10le"])
    x265 = ("keyint=100:min-keyint=100:scenecut=0:repeat-headers=1"
            ":colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc:range=limited:log-level=error")
    calistir(FF + ["-f", "rawvideo", "-pix_fmt", "yuv420p10le", "-s", f"{w}x{h}", "-framerate", "50",
                   "-stream_loop", "-1", "-i", "kare.yuv",
                   "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                   "-vf", vf, "-t", str(SURE),
                   "-c:v", "libx265", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p10le",
                   "-profile:v", "main10", "-tag:v", "hvc1", "-x265-params", x265,
                   "-colorspace", "bt2020nc", "-color_primaries", "bt2020", "-color_trc", "arib-std-b67",
                   "-color_range", "tv", *aac(), *HLS_FMP4(hedef)], cwd=is_)


def v04(is_: Path, hedef: Path, v: dict):
    w, h = 1920, 1080
    k = Kare(w, h, (64, 512, 512))
    k.bant(140, 340, lambda x: ycc709(*(3 * [x / (w - 1)])))
    # Karanlik rampa: 10 bit kod 64..127 (64 basamak). 8 bitte ayni aralik 16 basamak.
    k.bant(420, 620, lambda x: (64 + x * 64 // w, 512, 512))
    k.bant(700, 900, lambda x: (64 + (x * 64 // w) // 4 * 4, 512, 512))  # 8 bite yuvarlanmis kopya
    k.yaz(is_ / "kare.yuv")
    vf = ",".join(baslik(v, boy=30) + [
        yazi("Full gray ramp, 10-bit codes 64-940", "30", "350", 28),
        yazi("Dark ramp, 10-bit: 64 steps. Should look smooth or show very fine steps.", "30", "630", 28),
        yazi("Same dark ramp rounded to 8-bit: 16 wide bands. If the upper ramp looks like this one, "
             "the chain is 8-bit.", "30", "910", 28),
        sayac(y="90", boy=30), "format=yuv420p10le"])
    calistir(FF + ["-f", "rawvideo", "-pix_fmt", "yuv420p10le", "-s", f"{w}x{h}", "-framerate", "25",
                   "-stream_loop", "-1", "-i", "kare.yuv",
                   "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                   "-vf", vf, "-t", str(SURE),
                   "-c:v", "libx265", "-preset", "medium", "-crf", "12", "-pix_fmt", "yuv420p10le",
                   "-profile:v", "main10", "-tag:v", "hvc1",
                   "-x265-params", "keyint=50:min-keyint=50:scenecut=0:repeat-headers=1:aq-mode=0"
                   ":colorprim=bt709:transfer=bt709:colormatrix=bt709:range=limited:log-level=error",
                   *BT709, *aac(), *HLS_FMP4(hedef)], cwd=is_)


KANAL51 = [("FL", "front left"), ("FC", "center"), ("FR", "front right"),
           ("SR", "surround right"), ("SL", "surround left"), ("LFE", None)]


def v05(is_: Path, hedef: Path, v: dict):
    dilim = 3
    sure = dilim * len(KANAL51)
    girdiler, fc = [], []
    for i, (kod, soz) in enumerate(KANAL51):
        if soz:
            flite(soz, is_ / f"k{i}.wav")
            girdiler += ["-i", f"k{i}.wav"]
            fc.append(f"[{len(girdiler) // 2}:a]adelay={i * dilim * 1000},apad=whole_dur={sure}[c{i}]")
        else:
            fc.append(f"aevalsrc='0.5*sin(2*PI*40*t)*between(t,{i * dilim},{i * dilim + 2})':s=48000:d={sure}[c{i}]")
    sira = {k: i for i, (k, _) in enumerate(KANAL51)}
    ad = ["FL", "FR", "FC", "LFE", "SL", "SR"]
    fc.append("".join(f"[c{sira[a]}]" for a in ad) +
              "join=inputs=6:channel_layout=5.1(side):map=" +
              "|".join(f"{j}.0-{a}" for j, a in enumerate(ad)) + "[a]")
    yer = {"FL": (360, 300), "FC": (860, 230), "FR": (1360, 300), "SR": (1460, 700),
           "SL": (260, 700), "LFE": (860, 760)}
    ciz = ["format=yuv420p"]
    for i, (kod, soz) in enumerate(KANAL51):
        x, y = yer[kod]
        ciz.append(f"drawbox=x={x}:y={y}:w=200:h=120:color=0x303030:t=fill")
        ciz.append(f"drawbox=x={x}:y={y}:w=200:h=120:color=0x2ecc71:t=fill:"
                   f"enable='between(t,{i * dilim},{i * dilim + dilim - 0.01})'")
        ciz.append(yazi(kod, str(x + 60), str(y + 35), 50, "white", False))
    ciz += baslik(v, boy=30) + [sayac(y="90", boy=30), yazi(
        "Each speaker in turn: FL, C, FR, SR, SL (voice), then LFE (40 Hz tone). "
        "Green box = the speaker that should play.", "30", "950", 28)]
    calistir(FF + ["-f", "lavfi", "-i", f"color=c=black:s=1920x1080:r=25:d={sure}", *girdiler,
                   "-filter_complex", ";".join(fc) + f";[0:v]{','.join(ciz)}[v]",
                   "-map", "[v]", "-map", "[a]", *x264(50), *BT709,
                   "-c:a", "ac3", "-b:a", "448k", "-ar", "48000", "-t", str(sure),
                   *HLS_TS(hedef)], cwd=is_)


VTT_EN = "WEBVTT\n\n" + "".join(
    f"00:00:{s:02d}.000 --> 00:00:{s + 2:02d}.000\nSubtitle track 1 (English), cue {s // 3 + 1}\n\n"
    for s in range(0, 18, 3)) + ("00:00:18.000 --> 00:00:20.000\n"
                                 "Unicode check: İıŞşĞğ çöü ß é\n\n")
VTT_AR = "WEBVTT\n\n" + "".join(
    f"00:00:{s:02d}.000 --> 00:00:{s + 2:02d}.000\nمسار الترجمة "
    f"الثاني ({s // 3 + 1})\n\n" for s in range(0, 21, 3) if s + 2 <= 20)


def v06(is_: Path, hedef: Path, v: dict):
    flite("audio track one", is_ / "a1.wav")
    flite("audio track two", is_ / "a2.wav")
    fc = (
        "[1:a]apad=whole_dur=3,aloop=loop=-1:size=144000,atrim=0:20,aresample=48000[x1];"
        "aevalsrc='0.05*sin(2*PI*440*t)':s=48000:d=20[t1];[x1][t1]amix=inputs=2:normalize=0,"
        "aformat=channel_layouts=stereo[a1];"
        "[2:a]apad=whole_dur=3,aloop=loop=-1:size=144000,atrim=0:20,aresample=48000[x2];"
        "aevalsrc='0.05*sin(2*PI*880*t)':s=48000:d=20[t2];[x2][t2]amix=inputs=2:normalize=0,"
        "aformat=channel_layouts=stereo[a2]"
    )
    vf = ",".join(["format=yuv420p"] + baslik(v, boy=30) + [sayac(y="90", boy=30), yazi(
        "Audio 1 (eng): voice says track one + 440 Hz. Audio 2 (deu tag): track two + 880 Hz. "
        "Subtitles: English and Arabic (RTL).", "30", "950", 26)])
    calistir(FF + ["-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=25:d=20", "-i", "a1.wav", "-i", "a2.wav",
                   "-filter_complex", fc + f";[0:v]{vf}[v]",
                   "-map", "[v]", "-map", "[a1]", "-map", "[a2]",
                   *x264(50), *BT709, "-c:a", "aac", "-b:a", "96k",
                   "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", "language=deu",
                   "-t", "20", "-f", "hls", "-hls_time", "4", "-hls_playlist_type", "vod",
                   "-master_pl_name", "index.m3u8",
                   "-hls_segment_filename", f"{hedef.as_posix()}/%v_seg_%03d.ts",
                   "-var_stream_map",
                   "v:0,agroup:aud,name:video "
                   "a:0,agroup:aud,language:eng,name:audio_eng,default:yes "
                   "a:1,agroup:aud,language:deu,name:audio_deu",
                   f"{hedef.as_posix()}/%v.m3u8"], cwd=is_)
    # ffmpeg'in HLS yazicisi altyaziyi yalniz video ile ayni varyantta tasiyor
    # ve varyant basina tek altyazi; iki dilli WebVTT grubu elle kurulur.
    # X-TIMESTAMP-MAP: video TS'sinin ilk PTS'i (ffmpeg varsayilani 1,4 sn).
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=start_pts", "-of", "csv=p=0", str(hedef / "video_seg_000.ts")],
                       capture_output=True, text=True)
    pts = int(r.stdout.split()[0].split(",")[0])
    for dil, metin in (("eng", VTT_EN), ("ara", VTT_AR)):
        govde = metin.replace("WEBVTT\n", f"WEBVTT\nX-TIMESTAMP-MAP=MPEGTS:{pts},LOCAL:00:00:00.000\n", 1)
        (hedef / f"sub_{dil}.vtt").write_bytes(govde.encode("utf-8"))
        (hedef / f"sub_{dil}.m3u8").write_bytes((
            "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:20\n#EXT-X-PLAYLIST-TYPE:VOD\n"
            "#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:20.000,\n" + f"sub_{dil}.vtt\n#EXT-X-ENDLIST\n").encode())
    ana = (hedef / "index.m3u8").read_text(encoding="utf-8").splitlines()
    cikis = []
    for satir in ana:
        if satir.startswith("#EXT-X-STREAM-INF"):
            satir += ',SUBTITLES="sub"'
            if not any(c.startswith("#EXT-X-MEDIA:TYPE=SUBTITLES") for c in cikis):
                cikis += [
                    '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="sub",NAME="English",LANGUAGE="en",'
                    'DEFAULT=YES,AUTOSELECT=YES,URI="sub_eng.m3u8"',
                    '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="sub",NAME="Arabic",LANGUAGE="ar",'
                    'DEFAULT=NO,AUTOSELECT=YES,URI="sub_ara.m3u8"']
        cikis.append(satir)
    (hedef / "index.m3u8").write_bytes(("\n".join(cikis) + "\n").encode())


def v07(is_: Path, hedef: Path, v: dict):
    # Her saniye t=k.000'da 2 kare (40 ms) beyaz flas ve 40 ms 1 kHz bip.
    # Cetvel: -200..+200 ms; isaretci saniye sinirinda 0'dan gecer. Bip
    # duyuldugunda isaretcinin durdugu yer gecikmedir.
    w = 1920
    olcek = 4  # piksel / ms
    cetvel = [f"drawbox=x={w // 2 + ms * olcek - 2}:y=600:w=4:h={60 if ms % 100 == 0 else 30}:color=white:t=fill"
              for ms in range(-200, 201, 20)]
    cetvel += [yazi(f"{ms:+d}" if ms else "0", str(w // 2 + ms * olcek - 30), "670", 30, "white", False)
               for ms in range(-200, 201, 100)]
    isaretci = kayan("0xff4040", 12, 80, f"{w // 2}+(mod(t+0.5,1)-0.5)*1000*{olcek}-6", "520",
                     "lt(abs(mod(t+0.5,1)-0.5),0.2)")
    flas = "drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='lt(mod(t,1),0.04)'"
    vf = ",".join(["format=yuv420p", flas] + cetvel + [isaretci] + baslik(v, boy=30) + [
        sayac(y="90", boy=30),
        yazi("White flash and beep happen together every second. When you hear the beep, read the red "
             "marker: + means audio late.", "30", "820", 28),
        yazi("Ruler in milliseconds. Lip sync tolerance (ITU-R BT.1359): audio up to 45 ms early or "
             "125 ms late.", "30", "870", 28)])
    calistir(FF + ["-f", "lavfi", "-i", f"color=c=0x202020:s=1920x1080:r=50:d={SURE}",
                   "-f", "lavfi", "-i",
                   f"aevalsrc='0.5*sin(2*PI*1000*t)*lt(mod(t,1),0.04)|0.5*sin(2*PI*1000*t)*lt(mod(t,1),0.04)'"
                   f":s=48000:d={SURE}:c=stereo",
                   "-vf", vf, *x264(100), *BT709, *aac(), "-t", str(SURE), *HLS_TS(hedef)], cwd=is_)


def v08(is_: Path, hedef: Path, v: dict, oran: str, gop: int):
    sure = 12
    # Dikey cubuk kare basina sabit 16 piksel kayar; 10 kutudan biri her kare
    # sirayla yanar. Fotografta iki kutu yanik = cift kare, bos = atlanmis kare.
    kutular = []
    for i in range(10):
        kutular.append(f"drawbox=x={360 + i * 120}:y=760:w=100:h=100:color=0x404040:t=fill")
        kutular.append(f"drawbox=x={360 + i * 120}:y=760:w=100:h=100:color=0xffd400:t=fill:"
                       f"enable='eq(mod(n,10),{i})'")
    cubuk = kayan("white", 24, 400, "mod(n*16,main_w)", "300")
    vf = ",".join(["format=yuv420p", cubuk] + kutular + baslik(v, boy=30) + [
        sayac(y="90", boy=30),
        yazi(f"{oran} fps. Bar moves 16 px every frame: motion must be even. Regular jerks = frame rate "
             "and display refresh not matched.", "30", "900", 26),
        yazi("Camera test: photo at 1/15 s or slower shows lit boxes. Gaps or doubled boxes = dropped or "
             "repeated frames.", "30", "950", 26)])
    calistir(FF + ["-f", "lavfi", "-i", f"color=c=0x101828:s=1920x1080:r={oran}:d={sure}",
                   "-f", "lavfi", "-i",
                   f"aevalsrc='0.08*sin(2*PI*660*t)*lt(mod(t,1),0.05)':s=48000:d={sure}",
                   "-vf", vf, *x264(gop), *BT709, *aac(), "-t", str(sure), *HLS_TS(hedef)], cwd=is_)


def v09(is_: Path, hedef: Path, v: dict):
    # 50p kaynak -> tinterlace=interleave_top ile 25 kare/50 alan, ust alan once.
    vf = ",".join([
        "format=yuv420p",
        kayan("white", 40, 500, "mod(n*24,main_w)", "200"),
        kayan("0xffd400", 300, 60, "main_w-mod(n*12,main_w)", "750"),
    ] + baslik(v, boy=30) + [
        yazi("Moving edges with comb teeth = no deinterlacing. Good players show 50 smooth motion steps "
             "per second.", "30", "900", 26),
        "tinterlace=mode=interleave_top", "setfield=tff"])
    calistir(FF + ["-f", "lavfi", "-i", f"color=c=0x202020:s=1920x1080:r=50:d={SURE}",
                   "-f", "lavfi", "-i",
                   f"aevalsrc='0.08*sin(2*PI*550*t)*lt(mod(t,1),0.05)':s=48000:d={SURE}",
                   "-vf", vf, "-r", "25",
                   "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
                   "-flags", "+ilme+ildct", "-field_order", "tt",
                   "-x264-params", "keyint=50:min-keyint=50:scenecut=0:tff=1:colorprim=bt709"
                   ":transfer=bt709:colormatrix=bt709",
                   *BT709, *aac(), "-t", str(SURE), *HLS_TS(hedef)], cwd=is_)


def v10(is_: Path, hedef: Path, v: dict):
    sure = 30
    vf = ",".join(["format=yuv420p"] + baslik(v, boy=30) + [
        sayac(y="90", boy=30),
        yazi("Keyframe only at 0, 10 and 20 s. Segments are 2 s and mostly start without one.", "30", "900", 26),
        yazi("Seek to 0:05: a good player shows a picture quickly (decodes from the previous keyframe) "
             "or waits; gray or green blocks = decoder fed mid-GOP.", "30", "950", 26)])
    calistir(FF + ["-f", "lavfi", "-i", f"testsrc2=s=1920x1080:r=25:d={sure}",
                   "-f", "lavfi", "-i", f"sine=f=440:r=48000:d={sure}",
                   "-vf", vf, *x264(250), *BT709, *aac(), "-t", str(sure),
                   "-f", "hls", "-hls_time", "2", "-hls_playlist_type", "vod",
                   "-hls_flags", "split_by_time", "-hls_segment_filename", str(hedef / "seg_%03d.ts"),
                   str(hedef / "index.m3u8")], cwd=is_)


def v11(is_: Path, hedef: Path, v: dict):
    parcalar = [("a", "1920x1080", 25, 0, 48000, "Part A: 1920x1080, 25 fps, 48 kHz"),
                ("b", "1280x720", 50, 1000, 44100, "Part B: 1280x720, 50 fps, 44.1 kHz, timestamps jump +1000 s"),
                ("c", "1920x1080", 25, 0, 48000, "Part C: back to 1920x1080, 25 fps, timestamps restart")]
    satirlar = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:4",
                "#EXT-X-PLAYLIST-TYPE:VOD", "#EXT-X-MEDIA-SEQUENCE:0"]
    for j, (ad, boyut, r, ofset, ar, metin) in enumerate(parcalar):
        vf = ",".join(["format=yuv420p"] + baslik(v, boy=26) + [
            sayac(y="80", boy=26), yazi(metin, "30", "h-140", 30),
            yazi("Playback should continue without freeze, black screen or lost audio.", "30", "h-190", 26)])
        calistir(FF + ["-f", "lavfi", "-i", f"testsrc2=s={boyut}:r={r}:d=8",
                       "-f", "lavfi", "-i", f"sine=f={440 * (j + 1)}:r={ar}:d=8",
                       "-vf", vf, *x264(r * 2), *BT709, "-c:a", "aac", "-b:a", "128k", "-ar", str(ar), "-ac", "2",
                       "-t", "8", "-f", "hls", "-hls_time", "4", "-hls_playlist_type", "vod",
                       "-hls_segment_filename", str(hedef / f"{ad}_%03d.ts"), "-output_ts_offset", str(ofset),
                       str(is_ / f"p{ad}.m3u8")], cwd=is_)
        govde = (is_ / f"p{ad}.m3u8").read_text(encoding="utf-8").splitlines()
        if j > 0:
            satirlar.append("#EXT-X-DISCONTINUITY")
        alinacak = False
        for s in govde:
            if s.startswith("#EXTINF"):
                satirlar.append(s)
                alinacak = True
            elif alinacak and s and not s.startswith("#"):
                satirlar.append(Path(s).name)
                alinacak = False
    satirlar.append("#EXT-X-ENDLIST")
    (hedef / "index.m3u8").write_text("\n".join(satirlar) + "\n", encoding="utf-8", newline="\n")


URETICI = {
    "01": v01, "02": v02, "03": v03, "04": v04, "05": v05, "06": v06, "07": v07,
    "08a": lambda i, h, v: v08(i, h, v, "24000/1001", 48),
    "08b": lambda i, h, v: v08(i, h, v, "25", 50),
    "08c": lambda i, h, v: v08(i, h, v, "50", 100),
    "08d": lambda i, h, v: v08(i, h, v, "60000/1001", 120),
    "09": v09, "10": v10, "11": v11,
    "12": None,  # bilerek dosya yok: 404 sinami
}


def medya(args):
    cikti = Path(args.cikti).resolve()
    cikti.mkdir(parents=True, exist_ok=True)
    secili = set(args.yalniz.split(",")) if args.yalniz else None
    ana_is = Path(args.is_dizini) if args.is_dizini else Path(tempfile.mkdtemp(prefix="testkit_"))
    for v in VEKTORLER:
        if secili and v["no"] not in secili:
            continue
        f = URETICI[v["no"]]
        if f is None:
            print(f"[{v['no']}] dosya yok (bilerek)")
            continue
        hedef = cikti / v["klasor"]
        if hedef.exists():
            shutil.rmtree(hedef)
        hedef.mkdir(parents=True)
        is_ = ana_is / v["klasor"]
        is_.mkdir(parents=True, exist_ok=True)
        shutil.copy(YAZI_TIPI, is_ / "font.ttf")
        print(f"[{v['no']}] {v['ad']}")
        f(is_, hedef, v)
        shutil.rmtree(is_, ignore_errors=True)
    if not args.is_dizini:
        shutil.rmtree(ana_is, ignore_errors=True)
    toplam = sum(p.stat().st_size for p in cikti.rglob("*") if p.is_file())
    print(f"toplam {toplam / 1e6:.1f} MB, {sum(1 for p in cikti.rglob('*') if p.is_file())} dosya -> {cikti}")


# --------------------------------------------------------------------------
# Listeler ve XMLTV
# --------------------------------------------------------------------------

def vektor_url(taban: str, v: dict) -> str:
    return f"{taban}/{v['klasor']}/index.m3u8"


def testkit_m3u(taban: str, epg: str, yuzey: str) -> str:
    s = [f'#EXTM3U x-tvg-url="{epg}"',
         f"# {KIT_ADI}. Synthetic test vectors, no channels, no third-party content. CC0 1.0.",
         f"# Expected results for every entry: {BEKLENEN_SONUC_URL}",
         f"# list: {yuzey}"]
    for v in VEKTORLER:
        s.append(f'#EXTINF:-1 tvg-id="{tvg_id(v)}" tvg-name="{v["ad"]}" group-title="{v["grup"]}",{v["ad"]}')
        s.append(vektor_url(taban, v))
    return "\n".join(s) + "\n"


def ayristirma_listeleri(taban: str) -> dict[str, bytes]:
    ref = vektor_url(taban, VEKTORLER[0])
    L: dict[str, bytes] = {}
    L["p01-attributes.m3u"] = ("\n".join([
        f'#EXTM3U x-tvg-url="{EPG_DINAMIK}"',
        '#EXTINF:-1 tvg-id="tk01.testkit" tvg-name="P01 all common attributes" tvg-logo="" '
        'tvg-chno="101" group-title="Parse: attributes",P01 all common attributes',
        ref,
        '#EXTINF:-1 TVG-ID="tk01.testkit" Group-Title="Parse: attributes",P01 upper-case attribute names',
        ref,
        '#EXTINF:-1 tvg-id="tk01.testkit" group-title="Parse: attributes" group-title="Parse: duplicate wins",'
        'P01 duplicate group-title attribute (which one wins?)',
        ref,
        '#EXTINF:-1,P01 no attributes at all',
        ref,
        '#EXTINF:0 tvg-id="tk01.testkit" group-title="Parse: attributes",P01 duration 0 instead of -1',
        ref,
    ]) + "\n").encode()
    L["p02-quotes-commas.m3u"] = ("\n".join([
        "#EXTM3U",
        '#EXTINF:-1 tvg-name="Comma, inside attribute" group-title="Parse: commas",'
        'P02 comma inside a quoted attribute',
        ref,
        '#EXTINF:-1 group-title="Parse: commas",P02 title with a comma, here',
        ref,
        '#EXTINF:-1 tvg-name="equals=sign" group-title="Parse: commas",P02 equals sign inside attribute',
        ref,
        "#EXTINF:-1 tvg-id=tk01.testkit group-title=Parse,P02 unquoted attributes",
        ref,
        "#EXTINF:-1 tvg-id='tk01.testkit' group-title='Parse: commas',P02 single-quoted attributes",
        ref,
    ]) + "\n").encode()
    uzun = "P03 long name " + " ".join(f"word{i:02d}" for i in range(1, 40))
    L["p03-utf8-rtl.m3u"] = ("\n".join([
        "#EXTM3U",
        '#EXTINF:-1 group-title="Parse: UTF-8",P03 اختبار الاتجاه (Arabic: right to left)',
        ref,
        '#EXTINF:-1 group-title="Parse: UTF-8",P03 Türkçe İıŞşĞğÇçÖöÜü',
        ref,
        '#EXTINF:-1 group-title="Parse: UTF-8",P03 日本語 中文 한국어',
        ref,
        '#EXTINF:-1 group-title="Parse: UTF-8",P03 emoji \U0001F4FA\U0001F3AC✅',
        ref,
        f'#EXTINF:-1 group-title="Parse: UTF-8",{uzun}',
        ref,
        '#EXTINF:-1 group-title="المجموعة",P03 group name in Arabic',
        ref,
    ]) + "\n").encode("utf-8")
    L["p04-bom-crlf.m3u"] = ("﻿" + "\r\n".join([
        "#EXTM3U",
        '#EXTINF:-1 tvg-id="tk01.testkit" group-title="Parse: BOM and CRLF",P04 file starts with UTF-8 BOM, CRLF line ends',
        ref,
        "",
        '#EXTINF:-1 group-title="Parse: BOM and CRLF",P04 after an empty line',
        ref,
    ]) + "\r\n").encode("utf-8")
    L["p05-catchup-shift.m3u"] = ("\n".join([
        f'#EXTM3U x-tvg-url="{EPG_DINAMIK}" tvg-shift="2" catchup="shift" catchup-days="3"',
        '#EXTINF:-1 tvg-id="tk01.testkit" group-title="Parse: EPG shift",P05 inherits header tvg-shift +2 h and catchup 3 days',
        ref,
        '#EXTINF:-1 tvg-id="tk01.testkit" tvg-shift="0" group-title="Parse: EPG shift",P05 channel tvg-shift 0 overrides header',
        ref,
        '#EXTINF:-1 tvg-id="tk01.testkit" tvg-shift="-1.5" catchup="append" catchup-days="7" '
        'catchup-source="?utc={utc}&lutc={lutc}" group-title="Parse: EPG shift",P05 tvg-shift -1.5 h, catchup append 7 days',
        ref,
        '#EXTINF:-1 tvg-id="tk01.testkit" catchup="disabled" group-title="Parse: EPG shift",P05 catchup disabled',
        ref,
    ]) + "\n").encode()
    L["p06-extgrp-options.m3u"] = ("\n".join([
        "#EXTM3U",
        "#EXTGRP:Parse: EXTGRP group",
        "#EXTINF:-1,P06 group from #EXTGRP line",
        ref,
        "#EXTINF:-1,P06 #EXTVLCOPT user agent line before the URL",
        "#EXTVLCOPT:http-user-agent=TestKit/1.0",
        ref,
        "#EXTINF:-1,P06 #KODIPROP line before the URL",
        "#KODIPROP:inputstream=inputstream.adaptive",
        ref,
        '#EXTINF:-1 group-title="Parse: options",P06 explicit group-title after #EXTGRP',
        ref,
    ]) + "\n").encode()
    s = [f'#EXTM3U x-tvg-url="{EPG_DINAMIK}"']
    for i in range(1, 2001):
        v = VEKTORLER[i % (len(VEKTORLER) - 1)]  # 404 vektoru buyuk listede yok
        s.append(f'#EXTINF:-1 tvg-id="{tvg_id(v)}" tvg-chno="{i}" group-title="Parse: large list {(i - 1) // 100 + 1:02d}",'
                 f"P07 entry {i:04d} of 2000 ({v['no']})")
        s.append(vektor_url(taban, v))
    L["p07-large-2000.m3u"] = ("\n".join(s) + "\n").encode()
    return L


def xmltv_damga(t: dt.datetime) -> str:
    return t.strftime("%Y%m%d%H%M%S +0000")


def xmltv(baslangic: dt.datetime, gun: int) -> str:
    from xml.sax.saxutils import escape
    s = ['<?xml version="1.0" encoding="UTF-8"?>',
         f'<tv generator-info-name="{KIT_ADI} static snapshot" source-info-url="https://nightmaretv.net/testkit/epg.xml">']
    for v in VEKTORLER:
        s.append(f'  <channel id="{tvg_id(v)}"><display-name>{escape(v["ad"])}</display-name></channel>')
    for v in VEKTORLER:
        for i in range(gun * 24):
            bas = baslangic + dt.timedelta(hours=i)
            son = bas + dt.timedelta(hours=1)
            baslik_ = f"Should start {bas:%H}:00 UTC ({bas:%a %d %b})"
            ar = "يجب أن يبدأ " + f"{bas:%H}:00 UTC"
            s.append(f'  <programme start="{xmltv_damga(bas)}" stop="{xmltv_damga(son)}" channel="{tvg_id(v)}">'
                     f'<title lang="en">{escape(baslik_)}</title><title lang="ar">{escape(ar)}</title>'
                     f'<desc lang="en">{escape(KIT_ADI)}. Compare this start time with your clock: '
                     f'an offset of whole hours means a time zone or tvg-shift problem.</desc></programme>')
    s.append("</tv>")
    return "\n".join(s) + "\n"


def yaz_lf(yol: Path, metin: str):
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_bytes(metin.encode("utf-8"))


def listeler(args):
    taban = args.taban.rstrip("/")
    # Ayni icerik, uc ad: hangi yuzeyden gelindigi istek sayisindan okunur.
    for ad, yuzey in (("testkit.m3u", "site"), ("testkit-gh.m3u", "github"), ("testkit-llm.m3u", "llms")):
        metin = testkit_m3u(taban, EPG_DINAMIK, yuzey)
        yaz_lf(KIT / ad, metin)
        yaz_lf(SITE / ad, metin)
    for ad, veri in ayristirma_listeleri(taban).items():
        (KIT / "parse").mkdir(parents=True, exist_ok=True)
        (KIT / "parse" / ad).write_bytes(veri)
    bugun = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    bas = dt.datetime.strptime(args.epg_baslangic, "%Y-%m-%d") if args.epg_baslangic else bugun
    yaz_lf(KIT / "epg" / "testkit-epg-snapshot.xml", xmltv(bas, args.epg_gun))
    print("listeler yazildi:", KIT, "ve", SITE)


# --------------------------------------------------------------------------
# ffprobe dogrulamasi
# --------------------------------------------------------------------------

def probe(yol: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                        "-analyzeduration", "20M", "-probesize", "50M", str(yol)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return json.loads(r.stdout or "{}")


def yan_veri(yol: Path) -> list:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-select_streams", "v:0",
                        "-read_intervals", "%+#1", "-show_frames", "-show_entries",
                        "frame=side_data_list,interlaced_frame,top_field_first,color_transfer", str(yol)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    f = json.loads(r.stdout or "{}").get("frames", [])
    return f


BEKLENEN = {
    "01": dict(v=dict(codec_name="h264", width=1920, height=1080, r_frame_rate="25/1", color_transfer="bt709"),
               a=[dict(codec_name="aac", channels=2)]),
    "02": dict(v=dict(codec_name="hevc", profile="Main 10", width=3840, height=2160, pix_fmt="yuv420p10le",
                      color_primaries="bt2020", color_transfer="smpte2084", color_space="bt2020nc"),
               yan=["Mastering display metadata", "Content light level metadata"]),
    "03": dict(v=dict(codec_name="hevc", profile="Main 10", width=1920, height=1080, r_frame_rate="50/1",
                      pix_fmt="yuv420p10le", color_primaries="bt2020", color_transfer="arib-std-b67")),
    "04": dict(v=dict(codec_name="hevc", profile="Main 10", pix_fmt="yuv420p10le", color_transfer="bt709")),
    "05": dict(v=dict(codec_name="h264"), a=[dict(codec_name="ac3", channels=6, channel_layout="5.1(side)")]),
    "06": dict(v=dict(codec_name="h264")),
    "07": dict(v=dict(codec_name="h264", r_frame_rate="50/1"), a=[dict(codec_name="aac", channels=2)]),
    "08a": dict(v=dict(r_frame_rate="24000/1001")),
    "08b": dict(v=dict(r_frame_rate="25/1")),
    "08c": dict(v=dict(r_frame_rate="50/1")),
    "08d": dict(v=dict(r_frame_rate="60000/1001")),
    "09": dict(v=dict(codec_name="h264", field_order="tt", r_frame_rate="25/1")),
    "10": dict(v=dict(codec_name="h264")),
    "11": dict(v=dict(codec_name="h264")),
}


def dogrula(args):
    cikti = Path(args.cikti).resolve()
    sonuc, hata = {}, 0
    for v in VEKTORLER:
        no = v["no"]
        if no == "12":
            sonuc[no] = dict(durum="bilerek yok (404)")
            continue
        d = cikti / v["klasor"]
        boyut = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
        kayit = dict(klasor=v["klasor"], bayt=boyut, dosya=sum(1 for _ in d.rglob("*")))
        if no == "06":
            # Ana liste ayrica: video, iki ses ve iki altyazi yayini.
            ana = (d / "index.m3u8").read_text(encoding="utf-8")
            kayit["master"] = dict(
                ses=ana.count("TYPE=AUDIO"), altyazi=ana.count("TYPE=SUBTITLES"))
            akislar = []
            for alt in ("video.m3u8", "audio_eng.m3u8", "audio_deu.m3u8", "sub_eng.m3u8", "sub_ara.m3u8"):
                if (d / alt).exists():
                    akislar += probe(d / alt).get("streams", [])
            p = dict(streams=akislar, format={})
        else:
            p = probe(d / "index.m3u8")
        vs = [s for s in p.get("streams", []) if s.get("codec_type") == "video"]
        as_ = [s for s in p.get("streams", []) if s.get("codec_type") == "audio"]
        ss = [s for s in p.get("streams", []) if s.get("codec_type") == "subtitle"]
        anahtar = ["codec_name", "profile", "width", "height", "pix_fmt", "r_frame_rate", "field_order",
                   "color_range", "color_space", "color_primaries", "color_transfer"]
        kayit["video"] = {k: vs[0].get(k) for k in anahtar} if vs else None
        kayit["audio"] = [{k: s.get(k) for k in ("codec_name", "channels", "channel_layout", "sample_rate")}
                          | {"language": s.get("tags", {}).get("language")} for s in as_]
        kayit["subtitles"] = [{"codec_name": s.get("codec_name"), "language": s.get("tags", {}).get("language")}
                              for s in ss]
        kayit["sure_sn"] = p.get("format", {}).get("duration")
        hedef_dosya = d / ("video.m3u8" if no == "06" else "index.m3u8")
        # HLS ayristiricisi alan sirasini aktarmiyor; ilk segmentten okunur.
        ilk = sorted(d.glob("*seg_000.*")) or sorted(d.glob("a_000.ts"))
        if ilk and kayit["video"] is not None:
            sp = probe(ilk[0]).get("streams", [])
            sv = [x for x in sp if x.get("codec_type") == "video"]
            if sv:
                for k in ("field_order", "color_transfer", "color_primaries", "color_space"):
                    if not kayit["video"].get(k) or kayit["video"].get(k) == "unknown":
                        kayit["video"][k] = sv[0].get(k)
        cerceve = yan_veri(hedef_dosya)
        yan = []
        if cerceve:
            for sd in cerceve[0].get("side_data_list", []) or []:
                yan.append(sd)
            kayit["ilk_kare"] = {k: cerceve[0].get(k) for k in ("interlaced_frame", "top_field_first")}
        kayit["side_data"] = yan
        # Beklenen degerler
        b = BEKLENEN.get(no, {})
        sapma = []
        for k, deger in b.get("v", {}).items():
            if not kayit["video"] or kayit["video"].get(k) != deger:
                sapma.append(f"video.{k}={kayit['video'].get(k) if kayit['video'] else None} (beklenen {deger})")
        for i, ab in enumerate(b.get("a", [])):
            gercek = kayit["audio"][i] if i < len(kayit["audio"]) else {}
            for k, deger in ab.items():
                if gercek.get(k) != deger:
                    sapma.append(f"audio{i}.{k}={gercek.get(k)} (beklenen {deger})")
        turler = [sd.get("side_data_type") for sd in yan]
        for t in b.get("yan", []):
            if t not in turler:
                sapma.append(f"yan veri yok: {t}")
        if no == "06" and (kayit["master"]["ses"] != 2 or kayit["master"]["altyazi"] != 2
                          or len(kayit["subtitles"]) != 2):
            sapma.append(f"master: {kayit['master']}")
        if no == "09" and not (kayit.get("ilk_kare", {}).get("interlaced_frame") == 1):
            sapma.append("ilk kare taramali degil")
        kayit["sapma"] = sapma
        kayit["durum"] = "GECTI" if not sapma else "KALDI"
        hata += bool(sapma)
        sonuc[no] = kayit
        print(f"[{no}] {kayit['durum']} {boyut / 1e6:.2f} MB {'; '.join(sapma)}")
    (KIT / "results").mkdir(parents=True, exist_ok=True)
    (KIT / "results" / "ffprobe.json").write_text(json.dumps(sonuc, indent=1, ensure_ascii=False) + "\n",
                                                   encoding="utf-8", newline="\n")
    toplam = sum(r.get("bayt", 0) for r in sonuc.values())
    print(f"toplam {toplam / 1e6:.1f} MB; kalan {hata}")
    raise SystemExit(1 if hata else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    alt = ap.add_subparsers(dest="komut", required=True)
    m = alt.add_parser("medya")
    m.add_argument("--cikti", default=str(KIT / "media" / "v1"))
    m.add_argument("--is-dizini", dest="is_dizini")
    m.add_argument("--yalniz", help="virgulle vektor numaralari, ornek 02,03")
    m.set_defaults(f=medya)
    l = alt.add_parser("listeler")
    l.add_argument("--taban", default=VARSAYILAN_TABAN)
    l.add_argument("--epg-baslangic", dest="epg_baslangic", help="YYYY-AA-GG (varsayilan bugun UTC)")
    l.add_argument("--epg-gun", dest="epg_gun", type=int, default=3)
    l.set_defaults(f=listeler)
    d = alt.add_parser("dogrula")
    d.add_argument("--cikti", default=str(KIT / "media" / "v1"))
    d.set_defaults(f=dogrula)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
