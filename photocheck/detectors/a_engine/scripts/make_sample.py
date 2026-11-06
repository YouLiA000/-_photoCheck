#!/usr/bin/env python
"""Generate **fictional** test samples: self-printed fake forms, fake numbers, self-made QR codes.

Spec card 0.5, privacy red line #5: demos always use fictional samples, never
someone else's real data. Every number below is computed, not taken from a person
(the ID check digit is derived with MOD 11-2, so it is "format-valid but belongs to
nobody").

The generator also records **ground truth at draw time** (`samples/gt/<image_id>.json`):
the boxes come from the drawing parameters (`ImageDraw.textbbox` / paste coordinates),
never from detector output - otherwise the evaluation is the detector proving itself.

The GT file holds **no plaintext**: only `kind` + `subtype` + `bbox`, never the digits,
so it can live in the repo. The numbers themselves stay as constants in this file and
are covered by unit tests when a value comparison is needed.

Purpose:
  - A self-tests K-03 / K-04 / K-05 / K-06 without waiting for C's dataset
  - input for `scripts/eval_detect.py` (R-02 baseline table)
  - backup material for the W8 demo recording

Usage:
    python scripts/make_sample.py                # write into samples/synthetic/ and samples/gt/
    python scripts/make_sample.py --out-dir /tmp/x
    python scripts/make_sample.py --no-gt        # images only, no ground truth
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
)

FAKE_ID = "110101199003070011"  # check digit from ISO 7064:1983 MOD 11-2, fictional
FAKE_PHONE = "13800138000"


def _font(size: int):
    from PIL import ImageFont

    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _qr_array(payload: str, target_px: int = 220):
    import cv2

    encoder = cv2.QRCodeEncoder_create()
    code = encoder.encode(payload)
    if code is None:
        raise RuntimeError(f"QR encoding failed: {payload!r}")
    return cv2.resize(code, (target_px, target_px), interpolation=cv2.INTER_NEAREST)


def _paste_qr(image, payload: str, xy: tuple[int, int], size: int = 220):
    import numpy as np
    from PIL import Image

    code = _qr_array(payload, size)
    rgb = np.stack([code] * 3, axis=-1) if code.ndim == 2 else code
    image.paste(Image.fromarray(rgb), xy)


def _text_bbox(draw, xy: tuple[int, int], text: str, font) -> list[int]:
    """Text ground truth: computed by PIL, never eyeballed."""
    x0, y0, x1, y1 = draw.textbbox(xy, text, font=font)
    return [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]


def _tail_bbox(draw, xy: tuple[int, int], prefix: str, tail: str, font) -> list[int]:
    """Annotate only the tail of a line (e.g. `公民身份号码：<digits>` -> digits only)."""
    x, y = xy
    x_tail = x + int(round(draw.textlength(prefix, font=font)))
    return _text_bbox(draw, (x_tail, y), tail, font)


def _write_gt(
    gt_dir: Path,
    image_id: str,
    image_path: Path,
    objects: list[dict[str, Any]],
    note: str = "",
) -> Path:
    from PIL import Image

    with Image.open(image_path) as im:
        width, height = im.size
    # The note is report data (Chinese, consistent with the other deliverables).
    doc = {
        "image_id": image_id,
        "image": image_path.name,
        "width": width,
        "height": height,
        "source": "synthetic_generated",
        "generator": "scripts/make_sample.py",
        "objects": objects,
        "negative": not objects,
        "note": note or "真值由生成参数直接记录，非检测结果反推；不含号码明文。",
    }
    gt_dir.mkdir(parents=True, exist_ok=True)
    path = gt_dir / f"{image_id}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def make_express(out: Path):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (900, 620), "white")
    draw = ImageDraw.Draw(img)
    title, body, small = _font(34), _font(26), _font(20)
    objects: list[dict[str, Any]] = []

    # The drawn strings are the document content under test, so they stay Chinese.
    draw.rectangle([20, 20, 880, 600], outline="black", width=3)
    draw.text((44, 44), "校园快递代收单（虚构样本）", font=title, fill="black")
    draw.line([(40, 100), (860, 100)], fill="black", width=2)

    rows = [
        ("运单号", "SF0000000000001"),
        ("收件人", "李小雁"),
        ("联系电话", FAKE_PHONE),
        ("收件地址", "某某大学 3 号宿舍楼 412 室"),
        ("取件码", "8-2-1123"),
    ]
    y = 130
    for label, value in rows:
        draw.text((50, y), f"{label}：", font=body, fill="black")
        draw.text((230, y), value, font=body, fill="black")
        if label == "联系电话":
            objects.append(
                {
                    "gt_id": "g-phone-1",
                    "kind": "text",
                    "subtype": "phone",
                    "bbox": _text_bbox(draw, (230, y), value, body),
                }
            )
        y += 52

    id_prefix = "公民身份号码（代取登记）："
    draw.text((50, 430), id_prefix + FAKE_ID, font=small, fill="black")
    objects.append(
        {
            "gt_id": "g-idcard-1",
            "kind": "text",
            "subtype": "idcard",
            "bbox": _tail_bbox(draw, (50, 430), id_prefix, FAKE_ID, small),
        }
    )
    draw.text((50, 470), "备注：本单为演示虚构数据，号码不对应任何真实个人", font=small, fill="gray")
    _paste_qr(img, f"https://example.com/pickup/{FAKE_PHONE}", (640, 300))
    objects.append(
        {
            "gt_id": "g-qr-1",
            "kind": "qr",
            "subtype": "qr_link",
            # Paste coordinates plus size are the ground truth (quiet zone included),
            # not a box recovered by decoding.
            "bbox": [640, 300, 220, 220],
        }
    )

    path = out / "express_001.png"
    img.save(path)
    return path, objects


def make_idcard(out: Path):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (760, 480), (232, 240, 250))
    draw = ImageDraw.Draw(img)
    name_font, body = _font(36), _font(26)
    objects: list[dict[str, Any]] = []

    draw.rectangle([20, 20, 740, 460], outline=(120, 150, 190), width=3)
    draw.text((50, 46), "居民身份证（虚构样本）", font=_font(28), fill=(60, 80, 120))
    draw.text((50, 130), "姓名  张小雁", font=name_font, fill="black")
    id_prefix = "公民身份号码  "
    draw.text((50, 200), f"{id_prefix}{FAKE_ID}", font=body, fill="black")
    objects.append(
        {
            "gt_id": "g-idcard-1",
            "kind": "text",
            "subtype": "idcard",
            "bbox": _tail_bbox(draw, (50, 200), id_prefix, FAKE_ID, body),
        }
    )
    draw.text((50, 260), "住址  某某省某某市某某区某某路 1 号", font=body, fill="black")
    draw.text((50, 330), "签发机关  某某市公安局某某分局", font=body, fill="black")
    draw.text((50, 400), "有效期限  2020.01.01-2040.01.01", font=body, fill="black")

    path = out / "idcard_001.png"
    img.save(path)
    return path, objects


def make_wifi_qr(out: Path):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (560, 640), "white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 30), "扫码连 Wi-Fi（虚构样本）", font=_font(30), fill="black")
    _paste_qr(img, "WIFI:S:Campus-Guest;T:WPA;P:demo1234;;", (120, 110), 320)
    draw.text((40, 470), "SSID：Campus-Guest", font=_font(24), fill="black")
    draw.text((40, 520), "密码：demo1234", font=_font(24), fill="black")

    objects = [
        {"gt_id": "g-qr-1", "kind": "qr", "subtype": "qr_wifi", "bbox": [120, 110, 320, 320]}
    ]

    path = out / "qr_wifi_001.png"
    img.save(path)
    return path, objects


def make_clean(out: Path):
    """Clean negative: text, no sensitive data, no codes. False alarms are caught here."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (800, 480), "white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 40), "社团活动通知（干净负样本）", font=_font(34), fill="black")
    lines = [
        "本周六下午三点在图书馆三楼报告厅举办分享会。",
        "主题：手机照片里的隐私边界。",
        "现场提供打印服务，可自带素材。",
        "报名人数上限 60 人，先到先得。",
    ]
    y = 130
    for line in lines:
        draw.text((40, y), line, font=_font(26), fill="black")
        y += 60

    path = out / "clean_001.png"
    img.save(path)
    return path, []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate fictional test samples and ground truth")
    parser.add_argument("--out-dir", default=str(ROOT / "samples" / "synthetic"))
    parser.add_argument("--gt-dir", default=str(ROOT / "samples" / "gt"))
    parser.add_argument("--no-gt", action="store_true", help="generate images only, no ground truth")
    args = parser.parse_args(argv)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    gt_dir = Path(args.gt_dir)

    makers = (make_express, make_idcard, make_wifi_qr, make_clean)
    for maker in makers:
        path, objects = maker(out)
        rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        if args.no_gt:
            print(f"generated {rel} ({len(objects)} gt object(s), not written)")
        else:
            gt_path = _write_gt(gt_dir, path.stem, path, objects)
            gt_rel = gt_path.relative_to(ROOT) if gt_path.is_relative_to(ROOT) else gt_path
            print(f"generated {rel}  +  {gt_rel} ({len(objects)} object(s))")

    print("\nReminder: these are self-made samples, fine for self-testing and demos, but do NOT")
    print("register them as official dataset samples - K-13 samples need C's numbering,")
    print("annotation and generation record. The GT files hold no plaintext digits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
