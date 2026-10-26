# Python port of WairToNow's decosects/ReadArptDgmPng.cs
#   Copyright (C) 2015, Mike Rieker, Beverly, MA USA, www.outerworldapps.com
#   GPL v2, http://www.gnu.org/licenses/gpl-2.0.html
#   https://github.com/mrieker/WairToNow/blob/github/decosects/ReadArptDgmPng.cs
#
# Reads an airport diagram PNG (page 1 of the FAA APD PDF rendered at 300dpi)
# and finds the lat/lon tick-marked lines, OCRs the lat/lon strings printed
# next to them, then computes affine transforms between pixels and lat/lon:
#
#   lon = tfwA * pixx + tfwC * pixy + tfwE
#   lat = tfwB * pixx + tfwD * pixy + tfwF
#   pixx = wftA * lon + wftC * lat + wftE
#   pixy = wftB * lon + wftD * lat + wftF
#
# The port intentionally replicates the C# behavior (including integer
# truncation semantics and known quirks) so it produces the same data as
# https://www.outerworldapps.com/WairToNowWork/avare_aptdiags.php

import math
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None

BORXLEFT = 78                   # border dimensions
BORXRITE = 1535
BORYTOP = 190
BORYBOT = 2285
BLOCK = 4                       # characters and line segments never have a BLOCK x BLOCK blob of black pixels
D09W = 13                       # digit recognition resolution width
D09H = 17                       # digit recognition resolution height
D09R = 3                        # pixel size of the learnt.png debug image
MAXGAP = 15                     # spacing between '1' '1' (as on KLAX diagram)
MAXWH = 50                      # maximum width and height of a character box
TICKLEN = 7                     # a tick mark on a lat/lon line must be at least this many pixels long
YOVER = 9                       # tops of characters must match this amount to be in the same string
VFYPIXERR = 70                  # some charts (eg ASE,BLI,GTB) are non-linear
VFYDEGERR = 0.1 / 60
VFYPIXRAT = 0.95                # pixels should be within 95% square, else add to notsquare list

DECO_MAXWH = 30                 # Deco.MAXWH in C#

CLUSTER_LINEFUZZ = 50           # distance between string and associated lat/lon line
CLUSTER_MINTICKS = 3            # minimum tick marks for a line to be accepted
CLUSTER_SEMITILT = 21           # maximum semi-tilt segments we will accept

# some charts simply contain broken/misread strings; keyed by "<csvoutid>:<string>"
BAD_STRINGS = {
    "KABY:31^32.0'": "31^32.0'N",
    "KACK:1^15.0'N": "41^15.0'N",
    "KATL:33^39'": "33^39'N",
    "KASE:106^51.30'W": "106^51.50'W",
    "KAVL:86^32.0'W": "82^32.0'W",
    "KAVP:41^20.0\"N": "41^20.0'N",
    "KAVP:41^20.5\"N": "41^20.5'N",
    "KAVP:75^43.0\"W": "75^43.0'W",
    "KAVP:75^43.5\"W": "75^43.5'W",
    "KAVP:75^44.0\"W": "75^44.0'W",
    "KBAZ:29^42'5'N": "29^42.5'N",
    "KBDR:1^09.5'N": "41^09.5'N",
    "KBNA:36^06'W": "36^06'N",
    "KBNA:36^07'W": "36^07'N",
    "KBNA:36^08'W": "36^08'N",
    "KBNA:36^09'W": "36^09'N",
    "KBPT:96^01.0'W": "94^01.0'W",
    "KCBF:1^16'N": "41^16'N",
    "KCHS:32^53'": "32^53'N",
    "KCIU:6^15'N": "46^15'N",
    "KDVL:48^06.5'W": "48^06.5'N",
    "KDVL:48^07.0'W": "48^07.0'N",
    "KDVL:48^07.5'W": "48^07.5'N",
    "KDVL:98^55.0W": "98^55.0'W",
    "KEAT:120^12.0'": "120^12.0'W",
    "KEAT:120^12.5'": "120^12.5'W",
    "KEAT:120^13.0'": "120^13.0'W",
    "KEAT:47^23.5'": "47^23.5'N",
    "KEAT:47^24.0'": "47^24.0'N",
    "KEAT:47^24.5'": "47^24.5'N",
    "KEOD:87^28'00\"W": "87^28'30\"W",
    "KEVB:29^02.5'W": "29^02.5'N",
    "KEVB:29^03.0'W": "29^03.0'N",
    "KEVB:29^03.5'W": "29^03.5'N",
    "KEVB:29^04.0'W": "29^04.0'N",
    "KFHB:0^37.0'N": "30^37.0'N",
    "KFMH:1^40.0'N": "41^40.0'N",
    "KFRG:73^24.5'": "73^24.5'W",
    "KFRG:73^25.0'": "73^25.0'W",
    "KFTK:37^54.30'N": "37^54.5'N",
    "KFTK:85^58.30'W": "85^58.5'W",
    "KGTB:44^05'N": "--",
    "KHDC:90^24.5'N": "90^24.5'W",
    "KHDC:90^25.0'N": "90^25.0'W",
    "KHDC:90^25.5'N": "90^25.5'W",
    "KHRT:86^41W": "86^41'W",
    "KLHW:11^54'N": "31^54'N",
    "KLHW:11^64'N": "31^54'N",
    "KLNS:40^07.0'W": "40^07.0'N",
    "KLNS:40^07.5'W": "40^07.5'N",
    "KLXT:38^58.0N": "38^58.0'N",
    "KMBL:44^16.0\"N": "44^16.0'N",
    "KMCN:31^41.5'N": "32^41.5'N",
    "KMCO:8^25'N": "28^25'N",
    "KMDW:1^46.5'N": "41^46.5'N",
    "KNSI:33'^14'N": "33^14'N",
    "KNSI:33^1S": "33^15'N",
    "KOGS:75^27'N": "75^27'W",
    "KOGS:75^28'N": "75^28'W",
    "KOZR:85^42'30\"": "85^42'30\"W",
    "KPAH:88^46.0'N": "88^46.0'W",
    "KPAH:88^46.5'N": "88^46.5'W",
    "KPAH:88^47.0'N": "88^47.0'W",
    "KPBG:73^27.0'N": "73^27.0'W",
    "KPBG:73^28.0'N": "73^28.0'W",
    "KPBG:73^29.0'N": "73^29.0'W",
    "KPIT:440^29'N": "40^29'N",
    "KPOB:^10'N": "35^10'N",
    "KPOB:79^^00'W": "79^00'W",
    "KPTK:2^39.5'N": "42^39.5'N",
    "KPVD:2112071^26.0'W": "71^26.0'W",
    "KRND:^29^31'N": "29^31'N",
    "KRND:29^3^'N": "29^32'N",
    "KSAV:2^08'N": "32^08'N",
    "KSBN:41^42.0'": "41^42.0'N",
    "KSEE:16^58.0'W": "116^58.0'W",
    "KSEE:6^58.0'W": "116^58.0'W",
    "KSFO:7^38'N": "37^38'N",
    "KSJC:121^55'N": "121^55'W",
    "KSJC:121^56'N": "121^56'W",
    "KTVL:8^53.5'N": "38^53.5'N",
    "KTVL:8^54.5'N": "38^54.5'N",
    "KVDF:82^20.05'W": "82^20.5'W",
    "KVPS:586^31'W": "86^31'W",
    "KWRB:83^36'": "83^36'W",
}

# non-square pixels; value is the computed non-square ratio
NOT_SQUARE = {
    "KHLR": 1.094,
    "KNYG": 0.664,
    "PADQ": 0.944,
}

# charts with just one latitude or longitude line
# key is the lowestlat,lowestlon strings; value is the missing lat or lon to add
ONE_LINERS = {
    "29^11'N,81^04'W": "29^12'N",           # KDAB
    "41^15'N,95^46'W": "41^16'N",           # KCBF
    "34^40'N,86^41'W": "86^41.5'W",         # KHUA
    "29^31.0'N,95^14.5'W": "95^15.0'W",     # KLVJ
    "40^02'N,74^21'W": "40^02.5'N",         # KNEL
}


def _tdiv(a, b):
    """C# integer division: truncates toward zero (python // floors)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def _trunc(v):
    """C# (int) cast of a double: truncates toward zero."""
    return int(v)


def _color_is_black(rgba):
    """rgba: (...,4) uint8 array -> uint8 array of 0/1"""
    return ((rgba[..., 3] > 200) & (rgba[..., 0] < 100) &
            (rgba[..., 1] < 100) & (rgba[..., 2] < 100)).astype(np.uint8)


class LongLine:
    """A lat/lon line consisting of several segments in the original chart."""

    def __init__(self):
        self.begx = 0
        self.begy = 0
        self.endx = 0
        self.endy = 0
        self.count = 0

    def matches(self, x, y):
        """See if the given x,y is inline with the existing line."""
        old_dx = self.endx - self.begx
        old_dy = self.endy - self.begy
        oldlen = math.sqrt(old_dx * old_dx + old_dy * old_dy)
        if oldlen == 0.0:
            # C# would compute NaN and the dot comparison comes out False
            return False
        olddx = old_dx / oldlen
        olddy = old_dy / oldlen

        new_dx = x - self.begx
        new_dy = y - self.begy
        newlen = math.sqrt(new_dx * new_dx + new_dy * new_dy)
        if newlen == 0.0:
            # C# would compute NaN and the dot comparison comes out False
            return False
        newdx = new_dx / newlen
        newdy = new_dy / newlen

        dot = abs(olddx * newdx + olddy * newdy)
        return dot >= math.cos(3.0 / 180.0 * math.pi)

    def insert(self, x, y):
        """Insert the given x,y into this line's definition."""
        self.count += 1

        dx = self.endx - self.begx
        dy = self.endy - self.begy
        absdx = dx if dx > 0 else -dx
        absdy = dy if dy > 0 else -dy
        if absdy > absdx:
            f = (y - self.begy) / dy
        else:
            f = (x - self.begx) / dx

        if f < 0.0:
            self.begx = x
            self.begy = y
        elif f > 1.0:
            self.endx = x
            self.endy = y


class Slope:
    """Collection of small line segments that have the same coarse slope."""

    def __init__(self, dx, dy):
        self.dx = dx
        self.dy = dy
        self.xys = []           # list of (x, y)
        self._long_lines = None

    def get_long_lines(self):
        if self._long_lines is None:
            self._long_lines = []
            for (x, y) in self.xys:
                line = None
                for ll in self._long_lines:
                    if ll.matches(x, y):
                        line = ll
                        break
                if line is None:
                    line = LongLine()
                    line.begx = x
                    line.begy = y
                    line.endx = x + self.dx
                    line.endy = y + self.dy
                    self._long_lines.append(line)
                line.insert(x, y)
        return self._long_lines

    def get_fine_slope(self):
        avgdx = 0
        avgdy = 0
        for line in self.get_long_lines():
            avgdx += line.endx - line.begx
            avgdy += line.endy - line.begy
        return avgdx, avgdy


class Given:
    """A lat/lon string given on the command line and about where it is in the image."""
    __slots__ = ("found", "x", "y", "s")

    def __init__(self, x, y, s):
        self.found = False
        self.x = x
        self.y = y
        self.s = s


class Deco:
    """A decoded character from the image and where it was found."""
    __slots__ = ("x", "y", "w", "h", "c", "grays")

    def __init__(self):
        self.x = 0
        self.y = 0
        self.w = 0
        self.h = 0
        self.c = "?"
        self.grays = None


class Cluster:
    """A lat/lon string recovered from the image pixels."""

    def __init__(self, owner, ll=None):
        self.owner = owner
        self.vertical = False       # string is vertical (when image portrait oriented)
        self.lox = 999999999        # upper left corner inclusive
        self.loy = 999999999
        self.hix = -1               # lower right corner exclusive
        self.hiy = -1
        self.decos = []
        self._lat_valid = False
        self._lon_valid = False
        self._lat = 0.0
        self._lon = 0.0
        self._cenx = -1
        self._ceny = -1
        if ll is not None:
            for c in ll:
                deco = Deco()
                deco.c = c
                self.decos.append(deco)

    def get_deco(self, i):
        if 0 <= i < len(self.decos):
            return self.decos[i]
        return None

    def set_center(self, cx, cy):
        self._cenx = cx
        self._ceny = cy

    def insert_deco(self, deco):
        if self.lox > deco.x:
            self.lox = deco.x
        if self.loy > deco.y:
            self.loy = deco.y
        if self.hix < deco.x + deco.w:
            self.hix = deco.x + deco.w
        if self.hiy < deco.y + deco.h:
            self.hiy = deco.y + deco.h
        for i, d in enumerate(self.decos):
            if deco.x < d.x:
                self.decos.insert(i, deco)
                return
        self.decos.append(deco)

    @property
    def result(self):
        chars = []
        for deco in self.decos:
            if deco.c == "'" and chars and chars[-1] == "'":
                chars[-1] = '"'
            else:
                chars.append(deco.c)
        r = "".join(chars)
        g = BAD_STRINGS.get(self.owner.csvoutid + ":" + r)
        if g is not None:
            r = g
        return r

    @property
    def is_lat_lon(self):
        """digits ^ digits [ . digits ] ' [ digits " ] { N | S | E | W }"""
        r = self.result
        if r.endswith("?"):
            r = r[:-1] + "N"
        r = r.replace("?", "0")
        r += "\0"

        i = 0
        c = r[i]; i += 1
        if not ("0" <= c <= "9"):
            return False
        while "0" <= c <= "9":
            c = r[i]; i += 1

        if c != "^":
            return False

        c = r[i]; i += 1
        if not ("0" <= c <= "9"):
            return False
        while "0" <= c <= "9":
            c = r[i]; i += 1

        if c == ".":
            c = r[i]; i += 1
            while "0" <= c <= "9":
                c = r[i]; i += 1

        if c != "'":
            return False

        c = r[i]; i += 1
        if "0" <= c <= "9":
            while "0" <= c <= "9":
                c = r[i]; i += 1
            while c not in "NSEW":
                if c not in "\"'^":
                    return False
                c = r[i]; i += 1

        if c not in "NSEW":
            return False

        return r[i] == "\0"

    @property
    def longitude(self):
        if not self._lon_valid:
            self._lon = self._lat_lon("E", "W")
            self._lon_valid = True
        return self._lon

    @property
    def latitude(self):
        if not self._lat_valid:
            self._lat = self._lat_lon("N", "S")
            self._lat_valid = True
        return self._lat

    def _lat_lon(self, pos, neg):
        if not self.is_lat_lon:
            return 0.0

        r = self.result
        end = r[-1]
        if end not in "NSEW":
            raise RuntimeError(r + " doesn't end in N, S, E or W")
        if end != pos and end != neg:
            return 0.0

        i = r.index("^")
        deg = int(r[:i])
        i += 1

        j = r.index("'")
        minstr = r[i:j]
        j += 1
        minute = float(minstr)

        k = j
        while "0" <= r[k] <= "9":
            k += 1
        sec = 0
        if k > j:
            sec = int(r[j:k])

        if deg >= 180 or minute >= 60 or sec >= 60:
            raise RuntimeError(r + " degrees, minutes or seconds out of range")

        value = deg + minute / 60 + sec / 3600
        if end == neg:
            value = -value
        return value

    @property
    def center_x(self):
        """X pixel of vertical tick-marked line associated with this string (0 if none)."""
        if self._cenx < 0:
            best_x = 0
            best_count = CLUSTER_MINTICKS - 1
            inix = self.lox
            limx = self.hix
            if self.vertical:
                inix -= CLUSTER_LINEFUZZ
                limx += CLUSTER_LINEFUZZ
            if inix < 0:
                inix = 0
            if limx >= self.owner.width:
                limx = self.owner.width - 1
            llv = self.owner.longlenverts
            for x in range(inix, limx + 1):
                if llv[x] > best_count:
                    best_x = x
                    best_count = llv[x]
            if best_x == 0:
                # look for a bunch of closely spaced long lines (slightly tilted chart)
                best_count = 0
                start_x = 0
                stop_x = 0
                for x in range(inix, limx + 1):
                    v = llv[x]
                    if v > 0:
                        if start_x == 0:
                            start_x = x
                        stop_x = x
                        best_count += v
                if best_count >= CLUSTER_MINTICKS and stop_x - start_x <= CLUSTER_SEMITILT:
                    best_x = (start_x + stop_x) // 2
            self._cenx = best_x
        return self._cenx

    @property
    def center_y(self):
        """Y pixel of horizontal tick-marked line associated with this string (0 if none)."""
        if self._ceny < 0:
            best_y = 0
            best_count = CLUSTER_MINTICKS - 1
            iniy = self.loy
            limy = self.hiy
            if not self.vertical:
                iniy -= CLUSTER_LINEFUZZ
                limy += CLUSTER_LINEFUZZ
            if iniy < 0:
                iniy = 0
            if limy >= self.owner.height:
                limy = self.owner.height - 1
            llh = self.owner.longlenhorzs
            for y in range(iniy, limy + 1):
                if llh[y] > best_count:
                    best_y = y
                    best_count = llh[y]
            if best_y == 0:
                best_count = 0
                start_y = 0
                stop_y = 0
                for y in range(iniy, limy + 1):
                    v = llh[y]
                    if v > 0:
                        if start_y == 0:
                            start_y = y
                        stop_y = y
                        best_count += v
                if best_count >= CLUSTER_MINTICKS and stop_y - start_y <= CLUSTER_SEMITILT:
                    best_y = (start_y + stop_y) // 2
            self._ceny = best_y
        return self._ceny

    def set_orientation(self, landscape):
        if not landscape and self.latitude != 0:
            self._cenx = 0
        if not landscape and self.longitude != 0:
            self._ceny = 0
        if landscape and self.latitude != 0:
            self._ceny = 0
        if landscape and self.longitude != 0:
            self._cenx = 0

    def zero_center_x(self):
        self._cenx = 0

    def zero_center_y(self):
        self._ceny = 0

    def __str__(self):
        return (self.result + ":" +
                " loxy=(" + str(self.lox) + "," + str(self.loy) + ")" +
                " hixy=(" + str(self.hix) + "," + str(self.hiy) + ")" +
                " cenXY=(" + str(self._cenx) + "," + str(self._ceny) + ")")


class ArptDgmPng:
    """Georeference one airport diagram png; see module docstring."""

    def __init__(self, pngname, csvoutid, learnt_path, verbose=False, givens=None):
        self.pngname = pngname
        self.csvoutid = csvoutid or ""
        self.learnt_path = learnt_path
        self.verbose = verbose
        self.givens = list(givens or [])

        self.slopes = {}            # (dx,dy) -> Slope
        self.clusters = []
        self.landscape = False
        self.port_box_list = []     # (x, y, w, h) character boxes in rotated image
        self.red_outlines = []      # outlines drawn around accepted boxes (persist into flips)
        self.counts = {}            # learned character -> count
        self.learnt = {}            # learned character -> int array [D09H,D09W]

    def process(self):
        """Returns (tfw, wft) 6-tuples on success, or None when learning.

        With givens, updates the learnt csv instead of building a transform.
        """
        self.find_lat_lon_lines()
        self.create_rotated_image()
        self.find_lat_lon_strings()
        if self.givens:
            self.build_learning()
            return None
        return self.build_xform_matrix()

    # ------------------------------------------------------------------
    # step 1: find position and slope of all lat/lon tick marked lines
    # ------------------------------------------------------------------

    def find_lat_lon_lines(self):
        img = Image.open(self.pngname).convert("RGBA")
        self.orig_rgba = np.asarray(img)
        self.orig_height, self.orig_width = self.orig_rgba.shape[:2]

        # get strict black/white pixel array for easier decoding
        self.blacks = _color_is_black(self.orig_rgba)
        self.height, self.width = self.blacks.shape

        # clear off border lines, they sometimes get confused with lat/lons
        self.clear_border_lines()

        # filter out every BLOCK x BLOCK or larger blob (runways, buildings, ...)
        self.clear_large_blobs()

        # filter out every little blob smaller than MAXWH (most characters)
        self.clear_small_blobs()

        # find sloped line segments with tick marks, trying various box sizes
        for self.slopesz in range(24, 45, 2):
            self.find_segments()

        if self.verbose:
            for sl in self.slopes.values():
                print("slope: %d/%d: %d" % (sl.dy, sl.dx, len(sl.xys)))

        # find slope that occurred the most times
        best_slope = None
        for sl in self.slopes.values():
            if best_slope is None or len(best_slope.xys) < len(sl.xys):
                best_slope = sl
        if best_slope is None:
            raise RuntimeError("no line segments found")
        self.best_slope = best_slope

        # take weighted average of the slopes of all those lines
        llsx_i, llsy_i = best_slope.get_fine_slope()
        self.lat_lon_slope_x = llsx_i
        self.lat_lon_slope_y = llsy_i
        llsl = math.sqrt(llsx_i * llsx_i + llsy_i * llsy_i)
        if llsl == 0.0:
            raise RuntimeError("no reciprocal slope found")
        llsx = llsx_i / llsl
        llsy = llsy_i / llsl

        # find reciprocal slope, assume it is the other of latitude/longitude
        recip_slope = None
        for sl in self.slopes.values():
            recipdx, recipdy = sl.get_fine_slope()
            recipl = math.sqrt(recipdx * recipdx + recipdy * recipdy)
            if recipl == 0.0:
                dot = float("nan")      # C# gets NaN here; NaN > x is False
            else:
                recipx = recipdx / recipl
                recipy = recipdy / recipl
                dot = abs(recipx * llsx + recipy * llsy)
            if dot > 2.0 / self.slopesz:
                continue
            if recip_slope is None or len(recip_slope.xys) < len(sl.xys):
                recip_slope = sl
        if recip_slope is None:
            raise RuntimeError("no reciprocal slope found")
        self.recip_slope = recip_slope

        # rotate slope by 90,180,270 into range -44..+45 degrees
        x = self.lat_lon_slope_x
        y = self.lat_lon_slope_y
        while (x | y) < 0:
            x, y = y, -x
        if y > x:
            x, y = y, -x
        self.lat_lon_slope_x = x
        self.lat_lon_slope_y = y
        if self.verbose:
            print("lat/lon slope = %d/%d" % (y, x))

    def clear_border_lines(self):
        """Clear border lines so they can't be confused as lat/lon lines."""
        b = self.blacks
        height, width = self.height, self.width
        if height <= BORYBOT or width <= BORXRITE:
            # C# would index out of range scanning the border
            raise RuntimeError("image too small for border scan")

        colfull = b[BORYTOP:BORYBOT + 1, :].all(axis=0)

        x = 0
        while not colfull[x]:
            x += 1
            if x > BORXLEFT:
                return
        while colfull[x]:
            x += 1
            if x > BORXLEFT:
                return
        b[:, 0:x] = 0

        x = width
        while True:
            x -= 1
            if colfull[x]:
                break
            if x <= BORXRITE:
                return
        while colfull[x]:
            x -= 1
            if x < BORXRITE:
                return
        b[:, x + 1:width] = 0

        rowfull = b[:, BORXLEFT:BORXRITE + 1].all(axis=1)

        y = 0
        while not rowfull[y]:
            y += 1
            if y > BORYTOP:
                return
        while rowfull[y]:
            y += 1
            if y > BORYTOP:
                return
        b[0:y, :] = 0

        y = height
        while True:
            y -= 1
            if rowfull[y]:
                break
            if y <= BORYBOT:
                return
        while rowfull[y]:
            y -= 1
            if y < BORYBOT:
                return
        b[y + 1:height, :] = 0

    def clear_large_blobs(self):
        """Wipe out blobs of black pixels that are at least BLOCK x BLOCK."""
        b = self.blacks
        h, w = self.height, self.width

        # window sums of BLOCK x BLOCK for all start positions
        s = np.zeros((h + 1, w + 1), np.int32)
        np.cumsum(np.cumsum(b, axis=0, dtype=np.int32), axis=1, out=s[1:, 1:])
        win = (s[BLOCK:, BLOCK:] - s[:-BLOCK, BLOCK:] -
               s[BLOCK:, :-BLOCK] + s[:-BLOCK, :-BLOCK])
        # C# only scans window starts y < h-BLOCK, x < w-BLOCK
        full = np.zeros_like(win, dtype=bool)
        full[:h - BLOCK, :w - BLOCK] = (win[:h - BLOCK, :w - BLOCK] == BLOCK * BLOCK)

        clear = np.zeros((h, w), dtype=bool)
        fh, fw = full.shape
        for yy in range(BLOCK):
            for xx in range(BLOCK):
                clear[yy:yy + fh, xx:xx + fw] |= full

        newb = b & ~clear
        # C# recomputes blacks[] from the bitmap only for y < h-BLOCK, x < w-BLOCK,
        # leaving stale values in the last BLOCK rows/columns
        b[0:h - BLOCK, 0:w - BLOCK] = newb[0:h - BLOCK, 0:w - BLOCK]

    def _blob_first_pixels(self):
        """Flat indices of the first (row-major) pixel of each 8-connected blob,
           ordered the way a row-major scan would first encounter each blob."""
        labels, nlab = ndimage.label(self.blacks, structure=np.ones((3, 3), np.int32))
        if nlab == 0:
            return []
        flat = labels.ravel()
        nz = np.flatnonzero(flat)
        labs = flat[nz]
        _, first_idx = np.unique(labs, return_index=True)
        first_pix = nz[first_idx]
        first_pix.sort()
        return first_pix

    def clear_small_blobs(self):
        """Locate boxes around things that might be characters and clear them out."""
        w = self.width
        for idx in self._blob_first_pixels():
            y, x = divmod(int(idx), w)
            if self.blacks[y, x] == 0:
                continue
            ok, xlef, xrit, ytop, ybot = self.expand_perimeter(x, x, y, y)
            if ok:
                self.blacks[ytop:ybot + 1, xlef:xrit + 1] = 0

    def expand_perimeter(self, xlef, xrit, ytop, ybot):
        """Expand a rectangular perimeter to enclose a blotch of black pixels.
           Returns (ok, xlef, xrit, ytop, ybot)."""
        b = self.blacks
        height, width = self.height, self.width

        while True:
            if xlef < 1 or ytop < 1 or xrit > width - 2 or ybot > height - 2:
                # C# would throw IndexOutOfRangeException probing the neighbors
                raise RuntimeError("blob at image edge")

            # if anything left of left edge is black, expand left edge
            a = b[ytop:ybot + 1, xlef]
            o = (b[ytop:ybot + 1, xlef - 1] |
                 b[ytop - 1:ybot, xlef - 1] |
                 b[ytop + 1:ybot + 2, xlef - 1])
            if (a & o).any():
                xlef -= 1
                if xlef > 0 and xrit - xlef < MAXWH:
                    continue
                return False, xlef, xrit, ytop, ybot

            # if anything right of right edge is black, expand right edge
            a = b[ytop:ybot + 1, xrit]
            o = (b[ytop:ybot + 1, xrit + 1] |
                 b[ytop - 1:ybot, xrit + 1] |
                 b[ytop + 1:ybot + 2, xrit + 1])
            if (a & o).any():
                xrit += 1
                if xrit < width - 1 and xrit - xlef < MAXWH:
                    continue
                return False, xlef, xrit, ytop, ybot

            # if anything above top edge is black, expand top edge
            a = b[ytop, xlef:xrit + 1]
            o = (b[ytop - 1, xlef:xrit + 1] |
                 b[ytop - 1, xlef - 1:xrit] |
                 b[ytop - 1, xlef + 1:xrit + 2])
            if (a & o).any():
                ytop -= 1
                if ytop > 0 and ybot - ytop < MAXWH:
                    continue
                return False, xlef, xrit, ytop, ybot

            # if anything below bottom edge is black, expand bottom edge
            a = b[ybot, xlef:xrit + 1]
            o = (b[ybot + 1, xlef:xrit + 1] |
                 b[ybot + 1, xlef - 1:xrit] |
                 b[ybot + 1, xlef + 1:xrit + 2])
            if (a & o).any():
                ybot += 1
                if ybot < height - 1 and ybot - ytop < MAXWH:
                    continue
                return False, xlef, xrit, ytop, ybot

            return True, xlef, xrit, ytop, ybot

    def _perimeter_offsets(self, slopesz):
        """TransitToXY offsets relative to box center for n = 0..4*slopesz-1."""
        s2 = slopesz // 2
        offx = np.empty(4 * slopesz, np.int32)
        offy = np.empty(4 * slopesz, np.int32)
        for n in range(4 * slopesz):
            edge, m = divmod(n, slopesz)
            if edge == 0:
                offy[n] = -s2
                offx[n] = -s2 + m
            elif edge == 1:
                offy[n] = -s2 + m
                offx[n] = s2
            elif edge == 2:
                offy[n] = s2
                offx[n] = s2 - m
            else:
                offy[n] = s2 - m
                offx[n] = -s2
        return offx, offy

    def find_segments(self):
        """Scan image for line segments of length slopesz with a centered tick mark.
           Enter them into self.slopes and clear the used pixels."""
        slopesz = self.slopesz
        s2 = slopesz // 2
        n4 = 4 * slopesz
        offx, offy = self._perimeter_offsets(slopesz)
        b = self.blacks
        height, width = self.height, self.width
        nsegs = 0

        for cy in range(s2, height - s2 - 1):
            row_xs = np.flatnonzero(b[cy, s2:width - s2 - 1])
            if row_xs.size == 0:
                continue
            for cx0 in row_xs:
                cx = int(cx0) + s2

                # make sure we (still) have a black pixel in center of box
                if b[cy, cx] == 0:
                    continue

                per = b[cy + offy, cx + offx]

                # find first white-to-black transition around edge of box
                wb = np.flatnonzero((per[:-1] == 0) & (per[1:] != 0)) + 1
                if wb.size == 0:
                    continue
                ni = int(wb[0])

                # there should be exactly four transitions around the edge
                ch = per != np.roll(per, 1)
                tpos = np.flatnonzero(ch)
                if tpos.size != 4:
                    continue

                # order transitions circularly starting at ni (white-to-black)
                k = int(np.nonzero(tpos == ni)[0][0])
                t0 = int(tpos[k])
                t1 = int(tpos[(k + 1) % 4])
                t2 = int(tpos[(k + 2) % 4])
                t3 = int(tpos[(k + 3) % 4])

                # make black-to-white transitions point to the black pixel
                t1 = (t1 + n4 - 1) % n4
                t3 = (t3 + n4 - 1) % n4

                # make sure the transitions are on opposite edges
                wbdiff = (n4 + t0 - t2) % n4
                bwdiff = (n4 + t1 - t3) % n4
                if wbdiff < 2 * slopesz - 1 or wbdiff > 2 * slopesz + 1:
                    continue
                if bwdiff < 2 * slopesz - 1 or bwdiff > 2 * slopesz + 1:
                    continue

                # get XY of all transitions and calculate slope of edges
                wb1x = cx + int(offx[t0]); wb1y = cy + int(offy[t0])
                bw1x = cx + int(offx[t1]); bw1y = cy + int(offy[t1])
                wb2x = cx + int(offx[t2]); wb2y = cy + int(offy[t2])
                bw2x = cx + int(offx[t3]); bw2y = cy + int(offy[t3])

                adx = wb2x - bw1x
                ady = wb2y - bw1y
                bdx = bw2x - wb1x
                bdy = bw2y - wb1y
                avgdx = _tdiv(adx + bdx, 2)
                avgdy = _tdiv(ady + bdy, 2)

                # check for centered tick mark
                if not self.has_centered_tick_mark(cx, cy, avgdx, avgdy):
                    continue

                # add segment to list of known slopes
                key = (avgdx, avgdy)
                sl = self.slopes.get(key)
                if sl is None:
                    sl = Slope(avgdx, avgdy)
                    self.slopes[key] = sl
                sl.xys.append((cx, cy))
                nsegs += 1

                # erase used pixels so they aren't matched again
                b[cy - s2:cy + s2, cx - s2:cx + s2] = 0

        return nsegs

    def has_centered_tick_mark(self, cx, cy, avgdx, avgdy):
        b = self.blacks
        absavgdx = -avgdx if avgdx < 0 else avgdx
        absavgdy = -avgdy if avgdy < 0 else avgdy

        if (absavgdy | absavgdx) == 0:
            return False

        if absavgdy > absavgdx:
            # more vertical than horizontal
            for linedy in range(3, TICKLEN + 1):
                linedx = _tdiv(linedy * avgdx, avgdy)
                nb = (b[cy - linedx, cx + linedy] | b[cy + linedx, cx - linedy] |
                      b[cy - linedx - 1, cx + linedy] | b[cy + linedx - 1, cx - linedy] |
                      b[cy - linedx + 1, cx + linedy] | b[cy + linedx + 1, cx - linedy])
                if nb == 0:
                    return False
        else:
            # more horizontal than vertical
            for linedx in range(3, TICKLEN + 1):
                linedy = _tdiv(linedx * avgdy, avgdx)
                nb = (b[cy - linedx, cx + linedy] | b[cy + linedx, cx - linedy] |
                      b[cy - linedx - 1, cx + linedy] | b[cy + linedx - 1, cx - linedy] |
                      b[cy - linedx + 1, cx + linedy] | b[cy + linedx + 1, cx - linedy])
                if nb == 0:
                    return False

        return True

    # ------------------------------------------------------------------
    # step 2: rotate image so lat/lon lines are vertical and horizontal
    # ------------------------------------------------------------------

    def create_rotated_image(self):
        ow, oh = self.orig_width, self.orig_height
        newwh = _trunc(max(ow, oh) * math.sqrt(2.0))
        self.port_width = newwh
        self.port_height = newwh

        dx = self.lat_lon_slope_x
        dy = self.lat_lon_slope_y
        d = math.sqrt(dx * dx + dy * dy)
        costh = dx / d
        sinth = dy / d

        # dst pixel -> src pixel (rotate about center), nearest with C# truncation
        cendst = np.arange(newwh, dtype=np.float64) - newwh // 2
        censrcx = np.trunc(costh * cendst[None, :] - sinth * cendst[:, None] + 0.5).astype(np.int64)
        censrcy = np.trunc(costh * cendst[:, None] + sinth * cendst[None, :] + 0.5).astype(np.int64)
        srcx = censrcx + ow // 2
        srcy = censrcy + oh // 2
        del censrcx, censrcy
        valid = (srcx >= 0) & (srcx < ow) & (srcy >= 0) & (srcy < oh)

        orig_black = _color_is_black(self.orig_rgba)
        port_black = np.zeros((newwh, newwh), np.uint8)
        port_black[valid] = orig_black[srcy[valid], srcx[valid]]
        del srcx, srcy, valid

        self.blacks = port_black
        self.width = newwh
        self.height = newwh

        # note where the horizontal and vertical lat/lon lines end up
        self.longlenhorzs = np.zeros(self.port_height, np.int64)
        self.longlenverts = np.zeros(self.port_width, np.int64)
        for sl in self.slopes.values():
            self.compute_vert_horz_lat_lons(sl)

    def rotate_image_point(self, ox, oy, dx, dy):
        d = math.sqrt(dx * dx + dy * dy)
        costh = dx / d
        sinth = dy / d

        ox -= self.orig_width // 2
        oy -= self.orig_height // 2

        rx = _trunc(costh * ox + sinth * oy + 0.5)
        ry = _trunc(costh * oy - sinth * ox + 0.5)

        rx += self.port_width // 2
        ry += self.port_height // 2
        return rx, ry

    def compute_vert_horz_lat_lons(self, slope):
        for line in slope.get_long_lines():
            begx, begy = self.rotate_image_point(line.begx, line.begy,
                                                 self.lat_lon_slope_x, self.lat_lon_slope_y)
            endx, endy = self.rotate_image_point(line.endx, line.endy,
                                                 self.lat_lon_slope_x, self.lat_lon_slope_y)
            xdiff = abs(begx - endx)
            ydiff = abs(begy - endy)

            # small X difference means vertical
            if xdiff <= ydiff // 16:
                xavg = (begx + endx) // 2
                if 0 <= xavg < self.port_width:
                    self.longlenverts[xavg] += ydiff

            # small Y difference means horizontal
            if ydiff <= xdiff // 16:
                yavg = (begy + endy) // 2
                if 0 <= yavg < self.port_height:
                    self.longlenhorzs[yavg] += xdiff

    # ------------------------------------------------------------------
    # step 3: find and decode all lat/lon strings in the rotated image
    # ------------------------------------------------------------------

    def find_lat_lon_strings(self):
        # read previously learned digit pixel patterns; a missing file means
        # this is the first diagram of a learning run
        if os.path.isfile(self.learnt_path):
            with open(self.learnt_path) as f:
                for line in f:
                    line = line.rstrip("\n")
                    if not line:
                        continue
                    tokens = line.split(",")
                    key = tokens[0][0]
                    self.counts[key] = int(tokens[1])
                    arr = np.array([int(t) for t in tokens[2:2 + D09H * D09W]],
                                   dtype=np.int64).reshape(D09H, D09W)
                    self.learnt[key] = arr

        port_black_orig = self.blacks.copy()

        # find all character boxes (portrait); mutates self.blacks and records
        # the red outlines the C# draws into the rotated bitmap
        if self.verbose:
            print("find character boxes")
        self.clusters = []
        self.landscape = False
        self.find_character_boxes()

        # the C# drew red outlines around accepted boxes into the rotated bitmap;
        # those pixels are no longer black for the subsequent scans
        v2 = port_black_orig
        pw, ph = self.port_width, self.port_height
        for (x1, y1, x2, y2) in self.red_outlines:
            xl = max(x1, 0); xr = min(x2, pw - 1)
            yt = max(y1, 0); yb = min(y2, ph - 1)
            if xl > xr or yt > yb:
                continue
            if 0 <= y1 < ph:
                v2[y1, xl:xr + 1] = 0
            if 0 <= y2 < ph:
                v2[y2, xl:xr + 1] = 0
            if 0 <= x1 < pw:
                v2[yt:yb + 1, x1] = 0
            if 0 <= x2 < pw:
                v2[yt:yb + 1, x2] = 0

        boxes = self.port_box_list

        # reverse landscape (rotated 90deg counter-clockwise) scan; see KNFL
        if self.verbose:
            print("reverse landscape scan")
        self.blacks = np.ascontiguousarray(np.rot90(v2, 1))
        self.boxes = [(y, pw - x - w, h, w) for (x, y, w, h) in boxes]
        self.clusters = []
        self.width = ph
        self.height = pw
        self.landscape = True
        self.decode_lat_lon_strings()
        rev_land_clusters = self.clusters

        # normal landscape (rotated 90deg clockwise) scan
        if self.verbose:
            print("normal landscape scan")
        self.blacks = np.ascontiguousarray(np.rot90(v2, 3))
        self.boxes = [(ph - y - h, x, h, w) for (x, y, w, h) in boxes]
        self.clusters = []
        self.width = ph
        self.height = pw
        self.landscape = True
        self.decode_lat_lon_strings()
        norm_land_clusters = self.clusters

        # reverse portrait (downside-up) scan
        if self.verbose:
            print("reverse portrait scan")
        self.blacks = np.ascontiguousarray(v2[::-1, ::-1])
        self.boxes = [(pw - x - w, ph - y - h, w, h) for (x, y, w, h) in boxes]
        self.clusters = []
        self.width = pw
        self.height = ph
        self.landscape = False
        self.decode_lat_lon_strings()
        rev_port_clusters = self.clusters

        # normal portrait scan
        if self.verbose:
            print("normal portrait scan")
        self.blacks = v2
        self.boxes = list(boxes)
        self.clusters = []
        self.width = pw
        self.height = ph
        self.landscape = False
        self.decode_lat_lon_strings()

        # convert all landscape/reversed cluster X,Y to portrait X,Y
        for cluster in rev_land_clusters:
            lox, loy, hix, hiy = cluster.lox, cluster.loy, cluster.hix, cluster.hiy
            cluster.lox = pw - 1 - hiy
            cluster.loy = lox
            cluster.hix = pw - 1 - loy
            cluster.hiy = hix
            self.clusters.append(cluster)
        for cluster in norm_land_clusters:
            lox, loy, hix, hiy = cluster.lox, cluster.loy, cluster.hix, cluster.hiy
            cluster.lox = loy
            cluster.loy = ph - 1 - hix
            cluster.hix = hiy
            cluster.hiy = ph - 1 - lox
            self.clusters.append(cluster)
        for cluster in rev_port_clusters:
            lox, loy, hix, hiy = cluster.lox, cluster.loy, cluster.hix, cluster.hiy
            cluster.lox = pw - hix
            cluster.loy = ph - hiy
            cluster.hix = pw - lox
            cluster.hiy = ph - loy
            self.clusters.append(cluster)

        # learning keeps every cluster; the axis cleanup is only for the transform
        if not self.givens:
            self.check_multiple_axis_refs()

        if self.verbose:
            for cluster in self.clusters:
                print("cluster " + str(cluster))

    def find_character_boxes(self):
        """Locate boxes around things that might be characters (portrait rotated image)."""
        self.port_box_list = []
        self.red_outlines = []
        for idx in self._blob_first_pixels():
            y, x = divmod(int(idx), self.width)
            if self.blacks[y, x] == 0:
                continue
            ok, xlef, xrit, ytop, ybot = self.expand_perimeter(x, x, y, y)
            if ok:
                ww = xrit - xlef + 1
                hh = ybot - ytop + 1
                if ww <= DECO_MAXWH and 1 < hh <= DECO_MAXWH:
                    self.port_box_list.append((xlef, ytop, ww, hh))
                    self.red_outlines.append((xlef - 1, ytop - 1, xrit + 1, ybot + 1))
                self.blacks[ytop:ybot + 1, xlef:xrit + 1] = 0

    def decode_lat_lon_strings(self):
        """Decode pixels to corresponding characters and strings."""
        self.all_decos = []
        self.all_deco_keys = []

        b = self.blacks
        for (x, y, w, h) in self.boxes:
            # sometimes a digit is followed immediately by the degree symbol;
            # if the lower right corner is blank, split the box in two
            if w > 17 and h > 17 and w > h - 2:
                best_a = 0
                best_w = 0
                best_h = 0
                wlim = w
                hh = 0
                while True:
                    hh += 1
                    if hh > h:
                        break
                    ww = 0
                    while True:
                        ww += 1
                        if ww > wlim:
                            break
                        if b[y + h - hh, x + w - ww] != 0:
                            break
                    ww -= 1
                    wlim = ww
                    aa = hh * ww
                    if aa > best_a:
                        best_a = aa
                        best_w = ww
                        best_h = hh
                if best_w > 8 and best_h > 8:
                    self.decode_character(x, y, w - best_w, h)
                    self.decode_character(x + w - best_w, y, best_w, h - best_h)
                    continue

            self.decode_character(x, y, w, h)

        self.gather_into_clusters()

    def decode_character(self, x, y, w, h):
        b = self.blacks
        grays = None

        if w <= 0 or w > DECO_MAXWH:
            return
        if h <= 0 or h > DECO_MAXWH:
            return

        # decimal point
        if w < 5 and h < 5:
            ch = "."

        # seconds (apostrophe) mark
        elif self.check_for_sec_mark(x, y, w, h):
            ch = "'"

        # degrees mark
        elif w < 13 and h < 13:
            ch = "^"

        # digit '1'
        elif self.check_for_one_digit(x, y, w, h):
            ch = "1"

        # something that needs to be decoded
        elif w > 7 and h > 13:
            grays = self.build_grays_array(x, y, w, h)
            ch = self.decode_grays_array(grays)

            # sometimes a 2 is misread as a 7; real 7's don't have any black
            # pixels in the lower right corner (see NUW 122^38'W)
            if ch == "7":
                nb = (int(b[y + h - 1, x + w - 1]) + int(b[y + h - 1, x + w - 2]) + int(b[y + h - 1, x + w - 3]) +
                      int(b[y + h - 2, x + w - 1]) + int(b[y + h - 2, x + w - 2]) + int(b[y + h - 2, x + w - 3]))
                if nb > 0:
                    ch = "2"

        # some garbage
        else:
            return

        deco = Deco()
        deco.x = x
        deco.y = y
        deco.w = w
        deco.h = h
        deco.c = ch
        deco.grays = grays

        # keep list sorted by ascending X value (Y value as minor key)
        key = (x, y)
        lo, hi = 0, len(self.all_deco_keys)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.all_deco_keys[mid] <= key:
                lo = mid + 1
            else:
                hi = mid
        self.all_decos.insert(lo, deco)
        self.all_deco_keys.insert(lo, key)

    def check_for_sec_mark(self, x, y, w, h):
        """See if we have an apostrophe character."""
        if w >= 7:
            return False
        if h >= 9:
            return False

        b = self.blacks

        # if there's a black spot in the center, it's an apostrophe
        xc = w / 2.0 + x
        yc = h / 2.0 + y
        xleft = _trunc(xc - 0.499)
        xrite = _trunc(xc + 0.499)
        ytop = _trunc(yc - 0.499)
        ybot = _trunc(yc + 0.499)
        c = (int(b[ytop, xleft]) + int(b[ytop, xrite]) +
             int(b[ybot, xleft]) + int(b[ybot, xrite]))
        if c >= 2:
            return True

        # if there is black in the upper left corner it's a degree mark
        # (the C# lower-right check is a no-op due to a loop variable bug)
        c = int(b[y:y + h // 2, x:x + w // 2].sum())
        return c == 0

    def check_for_one_digit(self, x, y, w, h):
        """See if we have a '1' digit character."""
        b = self.blacks
        if w < 3 or w > 9:
            return False
        if h < 15 or h > 25:
            return False
        if w * 16 >= h * 9:
            return False
        for yy in range(1, h - 1):
            if (b[y + yy, x + w - 1] | b[y + yy, x + w - 2] | b[y + yy, x + w - 3]) == 0:
                return False
        for xx in range(1, w - 1):
            if (b[y, x + xx] | b[y + 1, x + xx] | b[y + 2, x + xx]) == 0:
                return False
        # (C# increments y instead of yy here, so this almost never iterates)
        yy = 4
        yv = y
        while True:
            yv += 1
            if yv >= h:
                break
            if (b[yv + yy, x] | b[yv + yy, x + 1]) != 0:
                return False
        return True

    def build_grays_array(self, x, y, w, h):
        """Pixellate the given pixels into a D09H x D09W gray-scale array."""
        b = self.blacks
        dmax = h / D09H * w / D09W
        dubs = [[0.0] * D09W for _ in range(D09H)]
        for dy in range(D09H):
            blktop = h / D09H * dy
            blkbot = h / D09H * (dy + 1)
            for dx in range(D09W):
                blklef = w / D09W * dx
                blkrit = w / D09W * (dx + 1)
                by = int(blktop)
                while by < blkbot:
                    bx = int(blklef)
                    while bx < blkrit:
                        if b[y + by, x + bx] > 0:
                            z = 1.0
                            if by < blktop:
                                z *= blktop - by
                            if bx < blklef:
                                z *= blklef - bx
                            if by + 1 > blkbot:
                                z *= (by + 1) - blkbot
                            if bx + 1 > blkrit:
                                z *= (bx + 1) - blkrit
                            dubs[dy][dx] += z
                        bx += 1
                    by += 1

        grays = np.empty((D09H, D09W), np.float64)
        for dy in range(D09H):
            for dx in range(D09W):
                gray = _trunc((1.0 - dubs[dy][dx] / dmax) * 256.0)
                if gray < 0:
                    gray = 0
                if gray > 255:
                    gray = 255
                grays[dy, dx] = gray
        return grays

    def decode_grays_array(self, grays):
        """Decode a grays array to the character it represents.

        While learning, the given string supplies the character, so this
        returns '?' and the glyph is recorded for later.
        """
        best_char = "?"
        if self.givens:
            return best_char
        best_score = 0.0
        for c in sorted(self.counts.keys()):
            count = self.counts[c]
            if count > 0:
                diff = grays - self.learnt[c] / count
                score = float((diff * diff).sum())
                if best_char == "?" or score < best_score:
                    best_char = c
                    best_score = score
        return best_char

    def gather_into_clusters(self):
        """Gather the separate decoded characters into clusters."""
        while self.all_decos:
            deco = self.all_decos.pop(0)
            self.all_deco_keys.pop(0)

            # skip stray marks that look like ' and . (see BAB 39^07'N)
            if deco.c == "'" or deco.c == ".":
                continue

            cluster = Cluster(self)
            cluster.vertical = self.landscape

            while True:
                cluster.insert_deco(deco)
                if deco.c in ("N", "S", "E", "W"):
                    break

                advanced = False
                i = 0
                while i < len(self.all_decos):
                    dd = self.all_decos[i]
                    if dd.x > cluster.hix + MAXGAP:
                        break
                    if dd.x < cluster.hix - 2:
                        i += 1
                        continue

                    ydiff = dd.y - deco.y
                    if dd.c == ".":
                        # sometimes an apostrophe is misdecoded as a dot (HOP 36^40'N)
                        if -YOVER <= ydiff <= YOVER:
                            dd.c = "'"
                        else:
                            ydiff += dd.h - deco.h
                            if ydiff < -YOVER or ydiff > YOVER:
                                i += 1
                                continue
                        dd.y = deco.y
                        dd.h = deco.h
                    else:
                        if ydiff < -YOVER or ydiff > YOVER:
                            i += 1
                            continue

                    del self.all_decos[i]
                    del self.all_deco_keys[i]
                    deco = dd
                    advanced = True
                    break

                if not advanced:
                    break

            if self.verbose:
                print("cluster %d,%d <%s>" % (cluster.lox, cluster.loy, cluster.result))
            if cluster.is_lat_lon:
                self.clusters.append(cluster)

    def check_multiple_axis_refs(self):
        """If multiple lats or lons refer to the same tick line, clear the bogus refs."""
        lats_are_horiz = 0
        lats_are_vert = 0
        lons_are_horiz = 0
        lons_are_vert = 0

        for cluster in self.clusters:
            if cluster.latitude != 0:
                if cluster.center_x != 0:
                    lats_are_vert += 1
                if cluster.center_y != 0:
                    lats_are_horiz += 1
            if cluster.longitude != 0:
                if cluster.center_x != 0:
                    lons_are_vert += 1
                if cluster.center_y != 0:
                    lons_are_horiz += 1

        if self.verbose:
            print("latsAreHoriz =", lats_are_horiz)
            print("latsAreVert  =", lats_are_vert)
            print("lonsAreHoriz =", lons_are_horiz)
            print("lonsAreVert  =", lons_are_vert)

        port = (lons_are_vert + lats_are_horiz > lons_are_horiz + lats_are_vert)
        land = (lats_are_vert + lons_are_horiz > lats_are_horiz + lons_are_vert)
        if not port and not land:
            raise RuntimeError("can't determine if portrait or landscape orientation")
        self.landscape = land

        for cluster in self.clusters:
            if cluster.latitude != 0:
                if port:
                    cluster.zero_center_x()
                if land:
                    cluster.zero_center_y()
            if cluster.longitude != 0:
                if port:
                    cluster.zero_center_y()
                if land:
                    cluster.zero_center_x()

    def build_learning(self):
        """Add the given lat/lon strings into ReadArptDgmPng_learnt.csv.

        Matches each given string to a cluster near its rotated position.
        Punctuation and the digit '1' must already match. Every other
        character contributes its 13x17 gray glyph to that character's sum.
        """
        for gv in self.givens:
            rx, ry = self.rotate_image_point(gv.x, gv.y, self.lat_lon_slope_x, self.lat_lon_slope_y)
            for cl in self.clusters:
                result = cl.result
                if len(result) != len(gv.s):
                    continue
                if (rx - cl.lox) * (rx - cl.lox) + (ry - cl.loy) * (ry - cl.loy) > 100:
                    continue
                for i, c in enumerate(gv.s):
                    deco = cl.get_deco(i)
                    if deco.grays is None:
                        # not learnable; the decoded character must match
                        if deco.c != c:
                            break
                    else:
                        if c not in self.counts:
                            self.counts[c] = 0
                            self.learnt[c] = np.zeros((D09H, D09W), dtype=np.int64)
                        self.counts[c] += 1
                        self.learnt[c] += deco.grays.astype(np.int64)
                gv.found = True
                break

        for gv in self.givens:
            if not gv.found:
                print("given %d,%d=%s not found" % (gv.x, gv.y, gv.s))

        with open(self.learnt_path, "w") as f:
            for c in sorted(self.counts):
                cells = [c, str(int(self.counts[c]))]
                cells.extend(str(int(v)) for v in self.learnt[c].reshape(-1))
                f.write(",".join(cells) + "\n")

        # debug image of the averaged glyphs, same layout as the C# dump
        chars = sorted(self.counts)
        width = len(chars) * (D09R * D09W + 1) + 1
        height = D09R * D09H + 2
        img = Image.new("RGB", (width, height), (255, 192, 203))
        px = img.load()
        for j, c in enumerate(chars):
            count = self.counts[c]
            learntc = self.learnt[c]
            xc = j * (D09W * D09R + 1)
            for y in range(D09H):
                for x in range(D09W):
                    gray = int(learntc[y, x] // count) if count else 0
                    color = (gray, gray, gray)
                    for yy in range(D09R):
                        for xx in range(D09R):
                            px[xc + x * D09R + xx + 1, y * D09R + yy + 1] = color
        img.save(os.path.join(os.path.dirname(os.path.abspath(self.learnt_path)),
                              "ReadArptDgmPng_learnt.png"))

    # ------------------------------------------------------------------
    # step 4: build the latlon <-> pixel transformation matrices
    # ------------------------------------------------------------------

    def build_xform_matrix(self):
        if self.verbose:
            print("assuming " + ("landscape" if self.landscape else "portrait") + " orientation")

        for cluster in self.clusters:
            cluster.set_orientation(self.landscape)

        # find the lowest and highest lons and lats
        highest_lat = None
        highest_lon = None
        lowest_lat = None
        lowest_lon = None
        for cluster in self.clusters:
            if cluster.center_x == 0 and cluster.center_y == 0:
                continue
            lat = cluster.latitude
            lon = cluster.longitude
            if lat != 0:
                if highest_lat is None or highest_lat.latitude < lat:
                    highest_lat = cluster
                if lowest_lat is None or lowest_lat.latitude > lat:
                    lowest_lat = cluster
            if lon != 0:
                if highest_lon is None or highest_lon.longitude < lon:
                    highest_lon = cluster
                if lowest_lon is None or lowest_lon.longitude > lon:
                    lowest_lon = cluster

        # some charts only have one lat or lon line; fake the other assuming square pixels
        one_liner_value = None
        if lowest_lat is highest_lat or lowest_lon is highest_lon:
            if lowest_lat is None or lowest_lon is None or \
                    (lowest_lat is highest_lat and lowest_lon is highest_lon):
                raise RuntimeError("fewer than two lats or lons found")
            one_liner_value = ONE_LINERS.get(lowest_lat.result + "," + lowest_lon.result)
            if one_liner_value is None:
                raise RuntimeError("fewer than two lats or lons found")

        if highest_lat is lowest_lat:
            made_up_lat = Cluster(self, one_liner_value)
            f = made_up_lat.latitude - lowest_lat.latitude
            f /= highest_lon.longitude - lowest_lon.longitude
            f /= math.cos((lowest_lat.latitude + made_up_lat.latitude) / 360.0 * math.pi)
            made_up_lat_pix_x = _trunc((highest_lon.center_y - lowest_lon.center_y) * f + 0.5) + lowest_lat.center_x
            made_up_lat_pix_y = _trunc((highest_lon.center_x - lowest_lon.center_x) * f + 0.5) + lowest_lat.center_y
            made_up_lat.set_center(made_up_lat_pix_x, made_up_lat_pix_y)
            self.clusters.append(made_up_lat)
            if made_up_lat.latitude > lowest_lat.latitude:
                highest_lat = made_up_lat
            else:
                lowest_lat = made_up_lat

        if highest_lon is lowest_lon:
            made_up_lon = Cluster(self, one_liner_value)
            f = made_up_lon.longitude - lowest_lon.longitude
            f /= highest_lat.latitude - lowest_lat.latitude
            f *= math.cos((lowest_lat.latitude + highest_lat.latitude) / 360.0 * math.pi)
            made_up_lon_pix_x = _trunc((lowest_lat.center_y - highest_lat.center_y) * f + 0.5) + lowest_lon.center_x
            made_up_lon_pix_y = _trunc((lowest_lat.center_x - highest_lat.center_x) * f + 0.5) + lowest_lon.center_y
            made_up_lon.set_center(made_up_lon_pix_x, made_up_lon_pix_y)
            self.clusters.append(made_up_lon)
            if made_up_lon.longitude > lowest_lon.longitude:
                highest_lon = made_up_lon
            else:
                lowest_lon = made_up_lon

        lowest_lat_lat = lowest_lat.latitude
        highest_lat_lat = highest_lat.latitude
        lowest_lon_lon = lowest_lon.longitude
        highest_lon_lon = highest_lon.longitude

        lowest_lat_pixel_x = lowest_lat.center_x
        highest_lat_pixel_x = highest_lat.center_x
        lowest_lon_pixel_x = lowest_lon.center_x
        highest_lon_pixel_x = highest_lon.center_x

        lowest_lat_pixel_y = lowest_lat.center_y
        highest_lat_pixel_y = highest_lat.center_y
        lowest_lon_pixel_y = lowest_lon.center_y
        highest_lon_pixel_y = highest_lon.center_y

        if self.verbose:
            print(" lowestLat = %s = %s at rotated (%d,%d)" % (lowest_lat.result, lowest_lat_lat, lowest_lat_pixel_x, lowest_lat_pixel_y))
            print("highestLat = %s = %s at rotated (%d,%d)" % (highest_lat.result, highest_lat_lat, highest_lat_pixel_x, highest_lat_pixel_y))
            print(" lowestLon = %s = %s at rotated (%d,%d)" % (lowest_lon.result, lowest_lon_lon, lowest_lon_pixel_x, lowest_lon_pixel_y))
            print("highestLon = %s = %s at rotated (%d,%d)" % (highest_lon.result, highest_lon_lon, highest_lon_pixel_x, highest_lon_pixel_y))

        # for the rotated image:
        #   lon = tfwA * pixx + tfwC * pixy + tfwE
        #   lat = tfwB * pixx + tfwD * pixy + tfwF
        tfw_a = tfw_b = tfw_c = tfw_d = tfw_e = tfw_f = 0.0

        if highest_lon_pixel_x != lowest_lon_pixel_x:
            tfw_a = (highest_lon_lon - lowest_lon_lon) / (highest_lon_pixel_x - lowest_lon_pixel_x)
            tfw_e = highest_lon_lon - tfw_a * highest_lon_pixel_x
        if highest_lon_pixel_y != lowest_lon_pixel_y:
            tfw_c = (highest_lon_lon - lowest_lon_lon) / (highest_lon_pixel_y - lowest_lon_pixel_y)
            tfw_e = highest_lon_lon - tfw_c * highest_lon_pixel_y

        if highest_lat_pixel_x != lowest_lat_pixel_x:
            tfw_b = (highest_lat_lat - lowest_lat_lat) / (highest_lat_pixel_x - lowest_lat_pixel_x)
            tfw_f = highest_lat_lat - tfw_b * highest_lat_pixel_x
        if highest_lat_pixel_y != lowest_lat_pixel_y:
            tfw_d = (highest_lat_lat - lowest_lat_lat) / (highest_lat_pixel_y - lowest_lat_pixel_y)
            tfw_f = highest_lat_lat - tfw_d * highest_lat_pixel_y

        # validate by checking all decoded markers convert to their pixel number
        lat_clusters = []
        lon_clusters = []
        for cluster in self.clusters:
            if cluster.latitude != 0:
                lat_clusters.append(cluster)
            if cluster.longitude != 0:
                lon_clusters.append(cluster)

        bad = False
        for lon_clus in lon_clusters:
            for lat_clus in lat_clusters:
                lat = lat_clus.latitude
                lon = lon_clus.longitude
                pixx = lat_clus.center_x | lon_clus.center_x
                pixy = lat_clus.center_y | lon_clus.center_y

                comx = _trunc((tfw_d * lon - tfw_c * lat - tfw_d * tfw_e + tfw_c * tfw_f) /
                              (tfw_d * tfw_a - tfw_c * tfw_b) + 0.5)
                comy = _trunc((tfw_b * lon - tfw_a * lat - tfw_b * tfw_e + tfw_a * tfw_f) /
                              (tfw_b * tfw_c - tfw_a * tfw_d) + 0.5)
                if pixx == 0:
                    pixx = comx
                if pixy == 0:
                    pixy = comy
                clat = tfw_b * pixx + tfw_d * pixy + tfw_f
                clon = tfw_a * pixx + tfw_c * pixy + tfw_e

                comx -= pixx
                comy -= pixy
                clat -= lat
                clon -= lon

                if comx < -VFYPIXERR or comx > VFYPIXERR:
                    print("horizontal verify error", comx)
                    bad = True
                if comy < -VFYPIXERR or comy > VFYPIXERR:
                    print("vertical verify error", comy)
                    bad = True
                if clat < -VFYDEGERR or clat > VFYDEGERR:
                    print("latitude verify error", clat)
                    bad = True
                if clon < -VFYDEGERR or clon > VFYDEGERR:
                    print("longitude verify error", clon)
                    bad = True

        # also, lat and lon pixel sizes should be the same
        lonperpix = abs(tfw_a + tfw_c)      # only one of tfwA,tfwC is non-zero
        latperpix = abs(tfw_b + tfw_d)      # only one of tfwB,tfwD is non-zero
        latcosine = math.cos((highest_lat_lat + lowest_lat_lat) / 360.0 * math.pi)
        llperpixratio = lonperpix * latcosine / latperpix
        ratioshouldbe = NOT_SQUARE.get(self.csvoutid, 1.0)
        if self.verbose:
            print("lon per pix=%s, lat per pix=%s, ratio=%s, expecting=%s" %
                  (lonperpix, latperpix, llperpixratio, ratioshouldbe))
        llperpixratio /= ratioshouldbe
        if llperpixratio > 1.0:
            llperpixratio = 1.0 / llperpixratio
        if llperpixratio < VFYPIXRAT:
            print("pixels are not square", llperpixratio)
            bad = True

        if bad:
            raise RuntimeError("latlon <-> rotated pixel verify error")

        # Mo = Mr * TCAr * Rc * TACo such that Mo * Po = L
        # (converts a pixel in the original image directly to lat/lon)
        taco = [[1.0, 0.0, -self.orig_width / 2.0],
                [0.0, 1.0, -self.orig_height / 2.0],
                [0.0, 0.0, 1.0]]

        denom = math.sqrt(self.lat_lon_slope_x ** 2 + self.lat_lon_slope_y ** 2)
        costh = self.lat_lon_slope_x / denom
        sinth = self.lat_lon_slope_y / denom
        rc = [[costh, sinth, 0.0],
              [-sinth, costh, 0.0],
              [0.0, 0.0, 1.0]]

        tcar = [[1.0, 0.0, self.port_width / 2.0],
                [0.0, 1.0, self.port_height / 2.0],
                [0.0, 0.0, 1.0]]

        mr = [[tfw_a, tfw_c, tfw_e],
              [tfw_b, tfw_d, tfw_f],
              [0.0, 0.0, 1.0]]

        mo = _mat_mul(_mat_mul(mr, tcar), _mat_mul(rc, taco))

        tfw_a = mo[0][0]
        tfw_b = mo[1][0]
        tfw_c = mo[0][1]
        tfw_d = mo[1][1]
        tfw_e = mo[0][2]
        tfw_f = mo[1][2]

        # inverse converts a lat/lon to a pixel in the original image
        mo_inv = _mat_inv(mo)
        wft_a = mo_inv[0][0]
        wft_b = mo_inv[1][0]
        wft_c = mo_inv[0][1]
        wft_d = mo_inv[1][1]
        wft_e = mo_inv[0][2]
        wft_f = mo_inv[1][2]

        return ((tfw_a, tfw_b, tfw_c, tfw_d, tfw_e, tfw_f),
                (wft_a, wft_b, wft_c, wft_d, wft_e, wft_f))


def _mat_mul(a, b):
    arows = len(a)
    acols = len(a[0])
    brows = len(b)
    bcols = len(b[0])
    if acols != brows:
        raise RuntimeError("A cols != B rows")
    c = [[0.0] * bcols for _ in range(arows)]
    for crow in range(arows):
        for ccol in range(bcols):
            s = 0.0
            for i in range(acols):
                s += a[crow][i] * b[i][ccol]
            c[crow][ccol] = s
    return c


def _mat_inv(a):
    arows = len(a)
    if arows != len(a[0]):
        raise RuntimeError("A not square")

    t = [[0.0] * (2 * arows) for _ in range(arows)]
    for row in range(arows):
        for col in range(arows):
            t[row][col] = a[row][col]
        t[row][arows + row] = 1.0

    _row_reduce(t)

    return [[t[row][arows + col] for col in range(arows)] for row in range(arows)]


def _row_reduce(t):
    trows = len(t)
    tcols = len(t[0])

    for row in range(trows):
        pivot = t[row][row]
        if pivot == 0.0:
            swaprow = row
            while True:
                swaprow += 1
                if swaprow >= trows:
                    raise RuntimeError("not invertable")
                pivot = t[swaprow][row]
                if pivot != 0.0:
                    t[row], t[swaprow] = t[swaprow], t[row]
                    break
        if pivot != 1.0:
            for col in range(row, tcols):
                t[row][col] /= pivot

        for rr in range(row + 1, trows):
            pivot = t[rr][row]
            if pivot != 0.0:
                for cc in range(row, tcols):
                    t[rr][cc] -= pivot * t[row][cc]

    for row in range(trows - 1, -1, -1):
        for rr in range(row - 1, -1, -1):
            pivot = t[rr][row]
            if pivot != 0.0:
                for cc in range(row, tcols):
                    t[rr][cc] -= pivot * t[row][cc]

def _fmt(v):
    """C# double.ToString() general format: 15 significant digits."""
    return format(v, ".15g")


def _csv_line(csvoutid, tfw, wft):
    return csvoutid + "," + ",".join(_fmt(v) for v in tfw + wft)


def _usage():
    return (
        "usage: python3 read_arpt_dgm_png.py <png> -csvoutid <id> [-csvoutfile <file>] [-verbose]\n"
        "       python3 read_arpt_dgm_png.py <png> -givens x,y=string ... [-verbose]\n"
        "       geotag line is csvoutid,tfwA,tfwB,tfwC,tfwD,tfwE,tfwF,wftA,wftB,wftC,wftD,wftE,wftF\n"
        "       -givens reads and rewrites ./ReadArptDgmPng_learnt.csv"
    )


def _parse_given(text):
    comma = text.find(",")
    eq = text.find("=")
    if comma <= 0 or eq <= comma:
        return None
    return Given(int(text[:comma]), int(text[comma + 1:eq]), text[eq + 1:])


def main(argv):
    """Same invocation as ReadArptDgmPng.exe for a geotag line or a learning pass."""
    pngname = None
    csvoutfile = None
    csvoutid = None
    verbose = False
    givens = []
    i = 0
    args = argv[1:]
    while i < len(args):
        arg = args[i]
        if arg == "-csvoutfile":
            i += 1
            csvoutfile = args[i]
        elif arg == "-csvoutid":
            i += 1
            csvoutid = args[i]
        elif arg == "-verbose":
            verbose = True
        elif arg == "-givens":
            while i + 1 < len(args):
                given = _parse_given(args[i + 1])
                if given is None:
                    break
                givens.append(given)
                i += 1
        elif arg.startswith("-"):
            raise SystemExit(_usage())
        elif pngname is not None:
            raise SystemExit("only one png file")
        else:
            pngname = arg
        i += 1
    if pngname is None or (csvoutid is None and not givens):
        raise SystemExit(_usage())

    here = os.path.dirname(os.path.abspath(__file__))
    if givens:
        # successive diagrams accumulate, the same way ReadArptDgmPng_learn does
        learnt = os.path.abspath("ReadArptDgmPng_learnt.csv")
    else:
        learnt = os.path.join(here, "ReadArptDgmPng_learnt.csv")
    result = ArptDgmPng(pngname, csvoutid, learnt, verbose, givens).process()
    if result is None:
        return
    tfw, wft = result
    line = _csv_line(csvoutid, tfw, wft)
    if csvoutfile:
        with open(csvoutfile, "w") as f:
            f.write(line + "\n")
    else:
        print(line)


if __name__ == "__main__":
    main(sys.argv)
