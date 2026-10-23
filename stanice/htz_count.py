"""
Grain counting for the HTZ station — the same method as the web app's
pipeline, step for step, on numpy/OpenCV so a Raspberry Pi runs it in
seconds rather than the minute a browser would need there.

count(rgb) takes an RGB uint8 image (h, w, 3) already scaled to working size
and returns the marks plus the figures the result screen shows.
"""
import math

import cv2
import numpy as np

PEAK_MIN_FRAC = 0.52   # a peak must be this deep inside the shape, relative to a typical grain
PEAK_DIST_FRAC = 0.85  # never put two centres closer together than this
SADDLE_FRAC = 0.10     # how deep the valley between two centres must be
AREA_ROUND = 0.35      # 1.65 grains of area still counts as one


def _jsround(x):
    """Math.round of the web app: halves go up, not to even."""
    return np.floor(np.asarray(x) + 0.5)


def _median(values):
    a = np.sort(np.asarray(values, dtype=np.float64))
    if a.size == 0:
        return 0.0
    m = a.size >> 1
    return float(a[m]) if a.size % 2 else float((a[m - 1] + a[m]) / 2)


def _otsu(hist, total):
    s = float(np.dot(np.arange(256), hist))
    sum_b = 0.0
    w_b = 0
    best = -1.0
    thr = 0
    for t in range(256):
        w_b += int(hist[t])
        if not w_b:
            continue
        w_f = total - w_b
        if not w_f:
            break
        sum_b += t * float(hist[t])
        m_b = sum_b / w_b
        m_f = (s - sum_b) / w_f
        between = w_b * w_f * (m_b - m_f) * (m_b - m_f)
        if between > best:
            best = between
            thr = t
    return thr


def _blur3_u8(src):
    """3x3 box blur in two integer passes, truncating like the app's Uint8 buffers."""
    p = np.pad(src.astype(np.int32), ((0, 0), (1, 1)), mode="edge")
    tmp = (p[:, :-2] + p[:, 1:-1] + p[:, 2:]) // 3
    p = np.pad(tmp, ((1, 1), (0, 0)), mode="edge")
    return ((p[:-2] + p[1:-1] + p[2:]) // 3).astype(np.uint8)


def _blue_field(rgb):
    """How much less blue each pixel is than the blue tray; None if the tray is not blue."""
    r = rgb[..., 0].astype(np.float32)
    g = rgb[..., 1].astype(np.float32)
    b = rgb[..., 2].astype(np.float32)
    ratio = (b - np.maximum(r, g * 0.5)) / (r + g + b + 40)
    idx = np.clip(_jsround((ratio + 1) * 255), 0, 511).astype(np.int64)
    hist = np.bincount(idx.ravel(), minlength=512)
    k = int(np.argmax(np.cumsum(hist) > ratio.size / 2))
    tray = k / 255 - 1
    if tray < 0.08:
        return None
    return np.maximum(0, tray - ratio) * 300


def _background_field(rgb):
    """Fallback for a tray that is not blue: colour distance from local tile medians."""
    h, w = rgb.shape[:2]
    bs = max(40, int(_jsround(min(w, h) / 18)))
    nbx, nby = math.ceil(w / bs), math.ceil(h / bs)
    med = np.zeros((nby, nbx, 3), np.float32)
    for by in range(nby):
        for bx in range(nbx):
            tile = rgb[by * bs:min(h, (by + 1) * bs):2, bx * bs:min(w, (bx + 1) * bs):2].reshape(-1, 3)
            n = tile.shape[0]
            for c in range(3):
                hist = np.bincount(tile[:, c], minlength=256)
                med[by, bx, c] = int(np.argmax(np.cumsum(hist) > (n >> 1)))
    fx = np.clip(np.arange(w) / bs - 0.5, 0, nbx - 1)
    fy = np.clip(np.arange(h) / bs - 0.5, 0, nby - 1)
    x0 = np.floor(fx).astype(int); x1 = np.minimum(nbx - 1, x0 + 1); tx = (fx - x0)[None, :, None]
    y0 = np.floor(fy).astype(int); y1 = np.minimum(nby - 1, y0 + 1); ty = (fy - y0)[:, None, None]
    top = med[y0][:, x0] * (1 - tx) + med[y0][:, x1] * tx
    bot = med[y1][:, x0] * (1 - tx) + med[y1][:, x1] * tx
    bg = top * (1 - ty) + bot * ty
    return np.sqrt(((rgb.astype(np.float32) - bg) ** 2).sum(axis=2))


def _fill_small_holes(mask, max_hole):
    """Fill background pockets enclosed by grain, but only glint-sized ones."""
    n, lab, stats, _ = cv2.connectedComponentsWithStats((mask == 0).astype(np.uint8), connectivity=4)
    if n <= 1:
        return mask
    h, w = mask.shape
    edge = np.zeros(n, bool)
    edge[np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))] = True
    small = (stats[:, cv2.CC_STAT_AREA] <= max_hole) & ~edge
    small[0] = False  # label 0 is the grain itself
    out = mask.copy()
    out[small[lab] & (mask == 0)] = 1
    return out


def _outside_tray(mask, label, n_blobs):
    """Blobs whose outline mostly borders something other than the tray floor."""
    bg_n, bg = cv2.connectedComponents((mask == 0).astype(np.uint8), connectivity=4)
    bg_area = np.bincount(bg[mask == 0].ravel(), minlength=bg_n)
    tray = int(np.argmax(bg_area)) if bg_area.size else -1
    edge = np.zeros(n_blobs, np.int64)
    on_tray = np.zeros(n_blobs, np.int64)
    m = mask.astype(bool)
    # every background pixel with a grain pixel beside it, in each of 4 directions
    for dy, dx in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        ys = slice(max(0, -dy), m.shape[0] - max(0, dy))
        xs = slice(max(0, -dx), m.shape[1] - max(0, dx))
        yn = slice(max(0, dy), m.shape[0] - max(0, -dy))
        xn = slice(max(0, dx), m.shape[1] - max(0, -dx))
        pair = ~m[ys, xs] & m[yn, xn]
        labs = label[yn, xn][pair]
        edge += np.bincount(labs, minlength=n_blobs)[:n_blobs]
        t = (bg[ys, xs] == tray)[pair]
        on_tray += np.bincount(labs[t], minlength=n_blobs)[:n_blobs]
    return (edge > 0) & (on_tray < edge * 0.5)


def segment(rgb):
    h, w = rgb.shape[:2]
    dist = _blue_field(rgb)
    if dist is None:
        dist = _background_field(rgb)
    max_d = float(dist.max())
    if max_d < 24:
        return {"fail": "contrast"}

    norm = np.minimum(255, _jsround(dist * (255 / max_d))).astype(np.uint8)
    smooth = _blur3_u8(norm)
    thr = _otsu(np.bincount(smooth.ravel(), minlength=256), smooth.size)
    mask = (smooth > thr).astype(np.uint8)
    cover = float(mask.mean())
    if cover > 0.72:
        return {"fail": "cover"}

    mask = _fill_small_holes(mask, max(20, w * h / 20000))
    k = np.ones((3, 3), np.uint8)
    mask = cv2.dilate(cv2.erode(mask, k), k)   # snap thin bridges, drop specks, restore size

    n, label, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return {"fail": "empty"}
    label = label - 1                          # background becomes -1, blobs 0..n-2
    nb = n - 1
    area = stats[1:, cv2.CC_STAT_AREA]
    x0 = stats[1:, cv2.CC_STAT_LEFT]; y0 = stats[1:, cv2.CC_STAT_TOP]
    x1 = x0 + stats[1:, cv2.CC_STAT_WIDTH] - 1; y1 = y0 + stats[1:, cv2.CC_STAT_HEIGHT] - 1
    border = (x0 == 0) | (y0 == 0) | (x1 == w - 1) | (y1 == h - 1)
    off = _outside_tray(mask, np.maximum(label, 0), nb)

    floor = max(12, w * h / 90000)
    big = np.nonzero(area >= floor)[0]
    if not big.size:
        return {"fail": "empty"}
    med = _median(area[big])
    rim = 0
    kept = []
    for i in big:
        if area[i] < max(floor, med * 0.35):
            continue
        if off[i] or (border[i] and area[i] > med * 8):
            rim += 1
            continue
        kept.append(i)
    if not kept:
        return {"fail": "empty"}
    kept = np.array(kept)
    med = _median(area[kept])
    blobs = [{"id": int(i), "area": int(area[i]), "cx": float(cents[i + 1][0]), "cy": float(cents[i + 1][1]),
              "x0": int(x0[i]), "y0": int(y0[i]), "x1": int(x1[i]), "y1": int(y1[i]), "border": bool(border[i])}
             for i in kept]
    return {"blobs": blobs, "med": med, "cover": cover, "rim": rim, "mask": mask, "label": label, "w": w, "h": h}


def _same_grain(dist, ax, ay, bx, by, drop):
    steps = max(1, math.ceil(math.hypot(bx - ax, by - ay)))
    s = np.arange(steps + 1)
    xs = _jsround(ax + (bx - ax) * s / steps).astype(int)
    ys = _jsround(ay + (by - ay) * s / steps).astype(int)
    low = float(dist[ys, xs].min())
    lo = min(float(dist[ay, ax]), float(dist[by, bx]))
    return low > lo - drop


def _spread_centres(pts_x, pts_y, seeds, n):
    """n centres over a blob: the peaks found stay as seeds, missing ones start at
    the pixels farthest from any seed, then k-means."""
    step = max(1, len(pts_x) // 3000)
    xs = pts_x[::step].astype(np.float64)
    ys = pts_y[::step].astype(np.float64)
    c = [(float(p[0]), float(p[1])) for p in seeds]
    while len(c) < n:
        cx = np.array([q[0] for q in c]); cy = np.array([q[1] for q in c])
        d = ((xs[:, None] - cx[None]) ** 2 + (ys[:, None] - cy[None]) ** 2).min(axis=1)
        far = int(np.argmax(d))
        c.append((xs[far], ys[far]))
    cx = np.array([q[0] for q in c]); cy = np.array([q[1] for q in c])
    for _ in range(10):
        d = (xs[:, None] - cx[None]) ** 2 + (ys[:, None] - cy[None]) ** 2
        a = np.argmin(d, axis=1)
        for j in range(n):
            sel = a == j
            if sel.any():
                cx[j] = xs[sel].mean(); cy[j] = ys[sel].mean()
    return list(zip(cx.tolist(), cy.tolist()))


def to_marks(seg):
    blobs, med, label, mask = seg["blobs"], seg["med"], seg["label"], seg["mask"]
    h, w = mask.shape
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    for _ in range(2):
        dist = cv2.blur(dist, (3, 3), borderType=cv2.BORDER_REPLICATE)

    # blob pixels in scan order, as the app walks them
    pix = {}
    for b in blobs:
        sub = label[b["y0"]:b["y1"] + 1, b["x0"]:b["x1"] + 1] == b["id"]
        yy, xx = np.nonzero(sub)
        pix[b["id"]] = (xx + b["x0"], yy + b["y0"])

    singles = [b for b in blobs if med * 0.7 < b["area"] < med * 1.3]
    radii = [float(dist[pix[b["id"]][1], pix[b["id"]][0]].max()) for b in (singles if len(singles) >= 5 else blobs)]
    r0 = max(1.5, _median(radii))
    min_peak = r0 * PEAK_MIN_FRAC
    min_dist2 = max(2, r0 * PEAK_DIST_FRAC) ** 2
    drop = max(0.6, r0 * SADDLE_FRAC)

    # local maxima of the distance map, away from the frame edge
    lmax = (dist >= cv2.dilate(dist, np.ones((3, 3), np.uint8))) & (dist >= min_peak)
    lmax[0, :] = lmax[-1, :] = False
    lmax[:, 0] = lmax[:, -1] = False

    peaks_of = {}
    for b in blobs:
        xx, yy = pix[b["id"]]
        sel = lmax[yy, xx]
        cx, cy = xx[sel], yy[sel]
        order = np.argsort(-dist[cy, cx], kind="stable")
        peaks = []
        for o in order:
            x, y = int(cx[o]), int(cy[o])
            ok = True
            for px, py in peaks:
                if (px - x) ** 2 + (py - y) ** 2 < min_dist2 or _same_grain(dist, x, y, px, py, drop):
                    ok = False
                    break
            if ok:
                peaks.append((x, y))
        if not peaks:
            peaks.append((b["cx"], b["cy"]))   # too thin to peak — still one grain
        peaks_of[b["id"]] = peaks

    lone = [b["area"] for b in blobs if len(peaks_of[b["id"]]) == 1 and med * 0.75 < b["area"] < med * 1.4]
    unit = _median(lone) if len(lone) >= 5 else med

    marks = []
    split = border = 0
    for b in blobs:
        peaks = peaks_of[b["id"]]
        by_area = math.floor(b["area"] / unit + AREA_ROUND)
        if by_area > len(peaks):
            xx, yy = pix[b["id"]]
            peaks = _spread_centres(xx, yy, peaks, by_area)
        if len(peaks) > 1:
            split += len(peaks)
        if b["border"]:
            border += 1
        kind = "split" if len(peaks) > 1 else "one"
        for x, y in peaks:
            marks.append({"x": float(x), "y": float(y), "n": 1, "kind": kind})
    return {"marks": marks, "clustered": split, "border": border, "r0": r0}


def count(rgb):
    """Full count on an RGB image at working size. Returns the dict the web page expects."""
    seg = segment(rgb)
    if "fail" in seg:
        return {"fail": seg["fail"]}
    res = to_marks(seg)
    return {
        "marks": res["marks"], "clustered": res["clustered"], "border": res["border"],
        "r0": res["r0"], "rim": seg["rim"], "blobs": len(seg["blobs"]), "med": seg["med"],
        "cover": seg["cover"], "mask": seg["mask"],
    }
