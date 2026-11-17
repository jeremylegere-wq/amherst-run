"""Minimal reader for Cloud-Optimised GeoTIFFs over HTTP: just enough for NRCan's HRDEM LiDAR grids.

Supports (Big)TIFF, 512x512 float32 tiles, LZW (5) or no (1) compression, no predictor, and the
EPSG:3979 (NAD83(CSRS) / Canada Atlas Lambert) projection. Only the tiles that are asked for are downloaded
(HTTP range requests), so a town can be read out of a 57 GB province-wide file. Standard library + numpy only.
"""
import math
import os
import struct
import time
import urllib.request

import numpy as np

USER_AGENT = "amherst-run/0.1 (hobby game; LiDAR building heights)"


# ----------------------------------------------------------------------------- LZW (TIFF flavour)
def lzw_decode(data):
    """Decode TIFF LZW (MSB-first codes, 9-12 bits, 'early change')."""
    d = bytes(data) + b"\0\0\0"
    nbits = (len(data)) * 8
    out = bytearray()
    table = [bytes([i]) for i in range(256)] + [b"", b""]
    width, pos, prev = 9, 0, None
    while pos + width <= nbits:
        i = pos >> 3
        chunk = (d[i] << 16) | (d[i + 1] << 8) | d[i + 2]
        code = (chunk >> (24 - (pos & 7) - width)) & ((1 << width) - 1)
        pos += width
        if code == 256:                                   # clear
            del table[258:]
            width, prev = 9, None
            continue
        if code == 257:                                   # end of information
            break
        if prev is None:
            entry = table[code]
        else:
            entry = table[code] if code < len(table) else prev + prev[:1]
            table.append(prev + entry[:1])
            if len(table) >= (1 << width) - 1 and width < 12:
                width += 1
        out += entry
        prev = entry
    return bytes(out)


# ----------------------------------------------------------------------------- projection EPSG:3979
_A, _F = 6378137.0, 1 / 298.257222101                     # GRS80
_E = math.sqrt(2 * _F - _F * _F)


def _m(phi):
    return math.cos(phi) / math.sqrt(1 - (_E * math.sin(phi)) ** 2)


def _t(phi):
    s = _E * math.sin(phi)
    return math.tan(math.pi / 4 - phi / 2) / ((1 - s) / (1 + s)) ** (_E / 2)


_P1, _P2, _P0, _L0 = math.radians(49.0), math.radians(77.0), math.radians(49.0), math.radians(-95.0)
_N = (math.log(_m(_P1)) - math.log(_m(_P2))) / (math.log(_t(_P1)) - math.log(_t(_P2)))
_FF = _m(_P1) / (_N * _t(_P1) ** _N)
_RHO0 = _A * _FF * _t(_P0) ** _N


def lcc3979(lat, lon):
    """Latitude/longitude (degrees, numpy arrays or floats) -> EPSG:3979 metres (x, y). Lambert Conformal Conic 2SP."""
    phi, lam = np.radians(lat), np.radians(lon)
    s = _E * np.sin(phi)
    t = np.tan(np.pi / 4 - phi / 2) / ((1 - s) / (1 + s)) ** (_E / 2)
    rho = _A * _FF * t ** _N
    theta = _N * (lam - _L0)
    return rho * np.sin(theta), _RHO0 - rho * np.cos(theta)


# ----------------------------------------------------------------------------- COG over HTTP
class COG:
    def __init__(self, url, fetch=None, cache_dir=None, name="grid"):
        self.url = url
        self.fetch = fetch or self._http
        self.cache_dir = cache_dir                      # decoded tiles are kept here as .npy (optional)
        self.name = name
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
        self.tiles = {}
        self.bytes_read = 0
        head = self.fetch(url, 0, 65535)
        self._parse(head)

    def _http(self, url, start, end, tries=6):
        """One HTTP range request, retried with back-off (DNS hiccups and dropped connections happen on long runs)."""
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Range": "bytes=%d-%d" % (start, end)})
        for k in range(tries):
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = resp.read()
                if len(data) == end - start + 1:
                    return data
                err = IOError("short read: %d of %d bytes" % (len(data), end - start + 1))
            except OSError as e:                         # URLError, timeouts and connection resets are OSErrors
                err = e
            time.sleep(min(30.0, 1.5 * 2 ** k))
        raise err

    def _read(self, start, n):
        b = self.fetch(self.url, start, start + n - 1)
        self.bytes_read += len(b)
        return b

    def _parse(self, b):
        bo = "<" if b[:2] == b"II" else ">"
        big = struct.unpack(bo + "H", b[2:4])[0] == 43
        off = struct.unpack(bo + "Q", b[8:16])[0] if big else struct.unpack(bo + "I", b[4:8])[0]
        n = struct.unpack(bo + ("Q" if big else "H"), b[off:off + (8 if big else 2)])[0]
        p, esz = off + (8 if big else 2), (20 if big else 12)
        sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8, 16: 8}
        fmt = {1: "B", 3: "H", 4: "I", 11: "f", 12: "d", 16: "Q"}
        tags = {}
        for k in range(n):
            e = b[p + k * esz:p + (k + 1) * esz]
            if big:
                tag, typ, cnt = struct.unpack(bo + "HHQ", e[:12]); val = e[12:20]; inline = 8
            else:
                tag, typ, cnt = struct.unpack(bo + "HHI", e[:8]); val = e[8:12]; inline = 4
            total = sizes.get(typ, 1) * cnt
            if total <= inline:
                raw, at = val[:total], None
            else:
                at = struct.unpack(bo + ("Q" if big else "I"), val[:inline])[0]
                raw = b[at:at + total] if at + total <= len(b) else None
            tags[tag] = (typ, cnt, raw, at)

        def val(tag):
            typ, cnt, raw, _at = tags[tag]
            if typ == 2:
                return raw.decode("latin-1").strip("\0 ")
            return struct.unpack(bo + fmt[typ] * cnt, raw)

        self.bo, self.big = bo, big
        self.width, self.height = val(256)[0], val(257)[0]
        self.tw, self.th = val(322)[0], val(323)[0]
        self.compression = val(259)[0]
        pred = val(317)[0] if 317 in tags else 1
        if val(258)[0] != 32 or val(339)[0] != 3 or pred != 1 or self.compression not in (1, 5):
            raise ValueError("unsupported GeoTIFF layout (want float32, no predictor, LZW or none)")
        sx, sy = val(33550)[:2]
        tie = val(33922)
        self.x0, self.y0, self.sx, self.sy = tie[3] - tie[0] * sx, tie[4] + tie[1] * sy, sx, sy
        self.nodata = float(val(42113)) if 42113 in tags else None
        self.across = (self.width + self.tw - 1) // self.tw
        self._off_at, self._cnt_at = tags[324][3], tags[325][3]
        self._otype, self._ctype = tags[324][0], tags[325][0]       # the two tables can use different int sizes
        self._entries = {}

    def _tile_entry(self, ti, tj):
        """(byte offset, byte count) of tile column ti, row tj (rows of the index are fetched once each)."""
        if tj not in self._entries:
            k0 = tj * self.across

            def row(at, typ):
                w, c = (8, "Q") if typ == 16 else (4, "I")
                return struct.unpack(self.bo + c * self.across, self._read(at + k0 * w, self.across * w))
            offs, cnts = row(self._off_at, self._otype), row(self._cnt_at, self._ctype)
            self._entries[tj] = (offs, cnts)
        offs, cnts = self._entries[tj]
        return offs[ti], cnts[ti]

    def _cache_path(self, ti, tj, ext):
        return os.path.join(self.cache_dir, "%d_%d.%s" % (ti, tj, ext)) if self.cache_dir else None

    def cached(self, ti, tj):
        p = self._cache_path(ti, tj, "npy")
        return bool(p and (os.path.exists(p) or os.path.exists(self._cache_path(ti, tj, "empty"))))

    def download(self, ti, tj):
        """Fetch one tile's compressed bytes into the cache (no decoding). Returns the cache path or None if empty."""
        raw_path = self._cache_path(ti, tj, "raw")
        if self.cached(ti, tj) or (raw_path and os.path.exists(raw_path)):
            return raw_path
        off, cnt = self._tile_entry(ti, tj)
        if cnt == 0:
            open(self._cache_path(ti, tj, "empty"), "w").close()
            return None
        if cnt > 64 * 1024 * 1024:
            raise ValueError("tile %s claims %d bytes: the index was misread" % ((ti, tj), cnt))
        raw = self._read(off, cnt)
        with open(raw_path + ".part", "wb") as f:
            f.write(raw)
        os.replace(raw_path + ".part", raw_path)
        return raw_path

    def decode_spec(self):
        return (self.bo, self.tw, self.th, self.nodata, self.compression)

    def tile(self, ti, tj):
        """The decoded tile (numpy float32, NaN where there is no data), or None if the tile is empty."""
        key = (ti, tj)
        if key not in self.tiles and self.cache_dir:
            npy = self._cache_path(ti, tj, "npy")
            if os.path.exists(npy):
                self.tiles[key] = np.load(npy)
            elif os.path.exists(self._cache_path(ti, tj, "empty")):
                self.tiles[key] = None
            elif os.path.exists(self._cache_path(ti, tj, "raw")):
                decode_file(self._cache_path(ti, tj, "raw"), npy, self.decode_spec())
                self.tiles[key] = np.load(npy)
        if key not in self.tiles:
            off, cnt = self._tile_entry(ti, tj)
            if cnt > 64 * 1024 * 1024:
                raise ValueError("tile %s claims %d bytes: the index was misread" % (key, cnt))
            if cnt == 0:
                self.tiles[key] = None
            else:
                raw = self._read(off, cnt)
                if self.compression == 5:
                    raw = lzw_decode(raw)
                a = np.frombuffer(raw, dtype=self.bo + "f4", count=self.tw * self.th).reshape(self.th, self.tw).copy()
                if self.nodata is not None:
                    a[a == self.nodata] = np.nan
                self.tiles[key] = a
        return self.tiles[key]

    def pixel(self, x, y):
        """Projected metres -> (column, row) as integer numpy arrays (pixel-is-area)."""
        return (np.floor((np.asarray(x) - self.x0) / self.sx).astype(np.int64),
                np.floor((self.y0 - np.asarray(y)) / self.sy).astype(np.int64))

    def sample(self, x, y):
        """Values at projected points (numpy arrays). Loads the tiles it needs."""
        col, row = self.pixel(x, y)
        out = np.full(col.shape, np.nan, dtype=np.float32)
        ti, tj = col // self.tw, row // self.th
        for a, b in set(zip(ti.tolist(), tj.tolist())):
            if a < 0 or b < 0 or a >= self.across or b * self.th >= self.height:
                continue
            t = self.tile(a, b)
            if t is None:
                continue
            m = (ti == a) & (tj == b)
            out[m] = t[row[m] - b * self.th, col[m] - a * self.tw]
        return out


def decode_file(raw_path, npy_path, spec):
    """Decode one cached compressed tile into a .npy file (runs in a worker process; plain module function)."""
    bo, tw, th, nodata, compression = spec
    with open(raw_path, "rb") as f:
        raw = f.read()
    if compression == 5:
        raw = lzw_decode(raw)
    a = np.frombuffer(raw, dtype=bo + "f4", count=tw * th).reshape(th, tw).copy()
    if nodata is not None:
        a[a == nodata] = np.nan
    np.save(npy_path + ".part.npy", a)
    os.replace(npy_path + ".part.npy", npy_path)
    os.remove(raw_path)
    return npy_path
