from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MapPreprocessConfig:
    enabled: bool = True
    occ_threshold: int = 60
    free_threshold: int = 240
    median_size: int = 3
    open_px: int = 1
    close_px: int = 1
    edge: bool = True
    edge_thicken_px: int = 1
    keep_raw: bool = False


def _env_int(name: str, default: int, *, min_v: int, max_v: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        v = int(raw)
        return max(min_v, min(max_v, v))
    except Exception:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw not in ("0", "false", "False", "no", "NO", "off", "OFF")


def load_config_from_env() -> MapPreprocessConfig:
    """
    2DLidar/SLAMの地図PNGを、エリア矩形を書きやすい“線画”に寄せる前処理。

    環境変数（任意）:
      - MAP_PREPROCESS=1/0
      - MAP_OCC_THRESHOLD=0..255（占有(黒)判定の閾値）
      - MAP_FREE_THRESHOLD=0..255（自由(白)判定の閾値。未使用値はunknown扱いで白へ）
      - MAP_MEDIAN_SIZE=1..9（奇数推奨。ノイズ低減）
      - MAP_OPEN_PX=0..4（小さなゴミ除去）
      - MAP_CLOSE_PX=0..6（壁の切れ目を繋ぐ）
      - MAP_EDGE=1/0（輪郭線のみ描く）
      - MAP_EDGE_THICKEN_PX=0..6（輪郭を太くする）
      - MAP_KEEP_RAW=1/0（rawを .raw.png に退避）
    """
    enabled = _env_bool("MAP_PREPROCESS", True)
    occ_threshold = _env_int("MAP_OCC_THRESHOLD", 60, min_v=0, max_v=255)
    free_threshold = _env_int("MAP_FREE_THRESHOLD", 240, min_v=0, max_v=255)
    median_size = _env_int("MAP_MEDIAN_SIZE", 3, min_v=1, max_v=9)
    open_px = _env_int("MAP_OPEN_PX", 1, min_v=0, max_v=4)
    close_px = _env_int("MAP_CLOSE_PX", 1, min_v=0, max_v=6)
    edge = _env_bool("MAP_EDGE", True)
    edge_thicken_px = _env_int("MAP_EDGE_THICKEN_PX", 1, min_v=0, max_v=6)
    keep_raw = _env_bool("MAP_KEEP_RAW", False)
    return MapPreprocessConfig(
        enabled=enabled,
        occ_threshold=occ_threshold,
        free_threshold=free_threshold,
        median_size=median_size,
        open_px=open_px,
        close_px=close_px,
        edge=edge,
        edge_thicken_px=edge_thicken_px,
        keep_raw=keep_raw,
    )


def preprocess_map_png(
    in_path: str,
    out_path: str,
    *,
    config: Optional[MapPreprocessConfig] = None,
) -> bool:
    """
    in_path のPNGを読み、見やすい線画っぽいPNGとして out_path に保存する。
    成功したら True、前処理をスキップした/できなかったら False。
    """
    if config is None:
        config = load_config_from_env()
    if not config.enabled:
        return False

    try:
        from PIL import Image, ImageChops, ImageFilter, ImageOps  # type: ignore
    except Exception:
        # 依存が無い環境では無加工で通す
        return False

    if config.keep_raw and in_path == out_path:
        # 同一パスで上書きするケースを想定（raw退避）
        raw_path = f"{out_path}.raw.png"
        try:
            Image.open(in_path).save(raw_path)
        except Exception:
            pass

    img = Image.open(in_path)
    gray = img.convert("L")

    # 先にメディアンでゴマ塩ノイズを軽減（SLAMの占有格子でよく出る）
    if config.median_size >= 3 and config.median_size % 2 == 1:
        gray = gray.filter(ImageFilter.MedianFilter(size=config.median_size))

    # occupied(壁/棚など)をマスク化: occupied=255, background=0
    # ROS map.pgm だと occupied=0, unknown=205, free=254/255 が多い。
    # unknownは“白寄せ”にして視認性優先（必要なら閾値調整）。
    occ_thr = int(config.occ_threshold)
    free_thr = int(config.free_threshold)

    def to_occ(p: int) -> int:
        if p <= occ_thr:
            return 255
        if p >= free_thr:
            return 0
        return 0  # unknown -> 背景扱い（白）

    occ = gray.point(to_occ, mode="L")

    def px_to_filter_size(px: int) -> int:
        # PillowのMin/MaxFilterは奇数サイズ
        if px <= 0:
            return 0
        return px * 2 + 1

    # 小さいゴミを落とす（opening）
    open_size = px_to_filter_size(int(config.open_px))
    if open_size >= 3:
        occ = occ.filter(ImageFilter.MinFilter(size=open_size))  # erode
        occ = occ.filter(ImageFilter.MaxFilter(size=open_size))  # dilate

    # 壁の切れ目を繋ぐ（closing）
    close_size = px_to_filter_size(int(config.close_px))
    if close_size >= 3:
        occ = occ.filter(ImageFilter.MaxFilter(size=close_size))  # dilate
        occ = occ.filter(ImageFilter.MinFilter(size=close_size))  # erode

    if config.edge:
        # 輪郭線だけにする: (dilate - erode)
        edge_size = px_to_filter_size(1)
        dil = occ.filter(ImageFilter.MaxFilter(size=edge_size))
        ero = occ.filter(ImageFilter.MinFilter(size=edge_size))
        edges = ImageChops.difference(dil, ero)

        thicken_size = px_to_filter_size(int(config.edge_thicken_px))
        if thicken_size >= 3:
            edges = edges.filter(ImageFilter.MaxFilter(size=thicken_size))

        # 白背景に黒線
        out = ImageOps.invert(edges)
    else:
        # occupiedを黒ベタに（白背景）
        out = ImageOps.invert(occ)

    # 完全白は眩しいので、うっすらオフホワイトに寄せても良いが、ここではシンプルに白固定
    out = out.convert("RGB")
    out.save(out_path)
    return True

