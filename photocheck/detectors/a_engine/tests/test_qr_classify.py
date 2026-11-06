"""K-06 unit tests: 100% classification accuracy (a pure rule problem) plus three red lines -
no short-link expansion, no identity inference, no payload display.

The Chinese strings below are product-facing labels asserted against the UI contract.
"""

import pytest

from photocheck.detectors.a_engine.core.detect.qr_classify import classify, to_display_class


@pytest.mark.parametrize(
    ("payload", "subtype", "risk"),
    [
        ("https://u.wechat.com/EAxxxx", "qr_wechat_card", 3),
        ("BEGIN:VCARD\nVERSION:3.0\nFN:张三\nTEL:13800138000\nEND:VCARD", "qr_vcard", 3),
        ("MECARD:N:张三;TEL:13800138000;;", "qr_vcard", 3),
        ("wxp://f2f0abcdefg", "qr_wechat_pay", 3),
        ("https://qr.alipay.com/abc123", "qr_alipay", 3),
        ("alipays://platformapi/startapp?appId=20000067", "qr_alipay", 3),
        ("WIFI:S:MyHome;T:WPA;P:secret123;;", "qr_wifi", 3),
        ("https://example.com/article/42", "qr_link", 1),
        ("http://t.cn/abc", "qr_link", 1),
        ("hello world", "qr_unknown", 1),
        ("", "qr_unknown", 1),
    ],
)
def test_classify(payload, subtype, risk):
    cls = classify(payload)
    assert cls.subtype == subtype
    assert cls.risk == risk


def test_wifi_ssid_shown_but_not_password():
    cls = classify("WIFI:S:MyHome;T:WPA;P:secret123;;")
    assert cls.summary == "MyHome"
    assert "secret123" not in (cls.summary or "")
    assert "secret123" not in cls.note


def test_wifi_ssid_with_escape():
    cls = classify(r"WIFI:S:My\;Home;T:WPA;P:x;;")
    assert cls.summary == "My;Home"


def test_link_summary_is_domain_only():
    cls = classify("https://u.wechat.com/EAxxxx")
    assert cls.summary == "u.wechat.com"
    assert "EAxxxx" not in (cls.summary or "")


def test_short_link_domain_kept_and_not_expanded():
    cls = classify("http://t.cn/abc")
    assert cls.summary == "t.cn"
    assert "不展开" in cls.note


def test_no_identity_judgement():
    """Red line: never guess "whose card this is" - the note must not echo the name."""
    cls = classify("BEGIN:VCARD\nFN:张三\nTEL:13800138000\nEND:VCARD")
    assert "张三" not in cls.note
    assert cls.summary is None


@pytest.mark.parametrize(
    ("subtype", "display"),
    [
        ("qr_wechat_card", "名片 / 联系人"),
        ("qr_vcard", "名片 / 联系人"),
        ("qr_wechat_pay", "收款 / 支付"),
        ("qr_alipay", "收款 / 支付"),
        ("qr_wifi", "Wi-Fi"),
        ("qr_link", "普通链接"),
        ("qr_unknown", "未识别"),
        ("qr_geo", "未识别"),
        ("qr_code", "未识别"),
    ],
)
def test_display_class(subtype, display):
    assert to_display_class(subtype) == display


def test_geo_and_tel_classified_but_display_unknown():
    assert classify("geo:39.9,116.4").subtype == "qr_geo"
    assert classify("tel:+8613800138000").subtype == "qr_contact"
    assert to_display_class("qr_geo") == "未识别"
