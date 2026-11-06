"""K-06 QR content classification (owner: A). Pure rules, fully offline.

Red lines (spec K-06):
1. never expand a short link: the copy says "points to a domain (short links are
   not expanded offline)";
2. never try to identify whose card it is;
3. never show the full payload, only a safe summary such as the domain or SSID.

Two granularities on purpose. The v4 contract has 11 `qr` subtypes, while K-06
only requires 4 DISPLAY classes. `classify()` returns the fine-grained subtype
that goes into the record for later statistics; `to_display_class()` collapses it
to the 4 display buckets plus "unknown" for the UI and for eval.
`qr_geo` / `qr_contact` / `qr_wechat_group` exist in the contract enum but are not
part of the K-06 display set, so they map to "unknown".

NOTE: the Chinese strings in this file are product copy shown in the UI, not
comments. They are data and must stay exactly as they are.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from urllib.parse import urlparse

__all__ = ["QRClass", "classify", "to_display_class", "DISPLAY_CLASSES"]

# Five display buckets: the 4 K-06 classes plus "unknown"
DISPLAY_CLASSES: Final[tuple[str, ...]] = (
    "名片 / 联系人",
    "收款 / 支付",
    "Wi-Fi",
    "普通链接",
    "未识别",
)

_DISPLAY_BY_SUBTYPE: Final[dict[str, str]] = {
    "qr_wechat_card": "名片 / 联系人",
    "qr_vcard": "名片 / 联系人",
    "qr_wechat_pay": "收款 / 支付",
    "qr_alipay": "收款 / 支付",
    "qr_wifi": "Wi-Fi",
    "qr_link": "普通链接",
    # In the contract enum but outside the K-06 display set -> "unknown"
    "qr_wechat_group": "未识别",
    "qr_contact": "未识别",
    "qr_geo": "未识别",
    "qr_code": "未识别",
    "qr_unknown": "未识别",
}

_WECHAT_CARD_HOSTS: Final[tuple[str, ...]] = ("u.wechat.com", "u.weixin.qq.com")
_MAX_SUMMARY = 64


@dataclass(frozen=True)
class QRClass:
    subtype: str
    risk: int
    summary: str | None = None  # domain / SSID only, never the payload
    note: str = ""  # UI copy, never written into a record


def _domain(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.netloc or "").split("@")[-1].split(":")[0].strip().lower().rstrip(".")
    return host[:_MAX_SUMMARY] or None


def _parse_wifi_ssid(payload: str) -> str | None:
    """Extract the SSID from `WIFI:S:<ssid>;T:<auth>;P:<pass>;;`.

    Handles `\\;` escaping, which real payloads use for semicolons inside an SSID.
    """
    body = payload.split(":", 1)[1] if ":" in payload else ""
    fields: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            buf.append(body[i + 1])
            i += 2
            continue
        if ch == ";":
            fields.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if buf:
        fields.append("".join(buf))
    for field in fields:
        if field[:2].upper() == "S:":
            ssid = field[2:].strip()
            return ssid[:_MAX_SUMMARY] or None
    return None


def classify(payload: str) -> QRClass:
    """payload -> (subtype, risk, safe summary, UI note).

    Order matters: this is a rule chain where the first match wins, and the more
    specific formats must be tested before the generic http(s) case.
    """
    text = (payload or "").strip()
    if not text:
        return QRClass("qr_unknown", 1, None, "内容为空，无法判断类型，交用户确认")

    upper = text.upper()
    lower = text.lower()

    if upper.startswith("WIFI:"):
        return QRClass("qr_wifi", 3, _parse_wifi_ssid(text), "Wi-Fi 密码，扫码可连入")

    if lower.startswith("wxp://"):
        return QRClass("qr_wechat_pay", 3, None, "收款码，可能关联实名")

    if lower.startswith("alipays://"):
        return QRClass("qr_alipay", 3, None, "收款码，可能关联实名")

    if upper.startswith("BEGIN:VCARD") or upper.startswith("MECARD:"):
        return QRClass("qr_vcard", 3, None, "联系人卡，含姓名和电话")

    if lower.startswith("geo:"):
        return QRClass("qr_geo", 3, None, "含地理坐标，扫码可定位")

    if lower.startswith(("tel:", "sms:", "mailto:")):
        return QRClass("qr_contact", 3, None, "含直接联系方式（电话 / 邮件 / 短信）")

    if lower.startswith(("http://", "https://")):
        host = _domain(text)
        if host:
            if any(host == h or host.endswith("." + h) for h in _WECHAT_CARD_HOSTS):
                return QRClass("qr_wechat_card", 3, host, "微信名片，含姓名和电话")
            if host.endswith("weixin.qq.com") and "/g/" in text:
                return QRClass("qr_wechat_group", 3, host, "群邀请链接，入群后可看群资料")
            if host == "qr.alipay.com" or host.endswith(".alipay.com"):
                return QRClass("qr_alipay", 3, host, "收款码，可能关联实名")
            return QRClass("qr_link", 1, host, "指向某域名（离线不展开短链）")
        return QRClass("qr_link", 1, None, "指向某域名（离线不展开短链）")

    return QRClass("qr_unknown", 1, None, "无法判断类型，交用户确认")


def to_display_class(subtype: str) -> str:
    """Fine-grained subtype -> one of the 4 display classes, or "unknown"."""
    return _DISPLAY_BY_SUBTYPE.get(subtype, "未识别")
