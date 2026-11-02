"""PhotoCheck 共享契约 v4 —— 记录类型与硬校验（A 侧只产出 ImageDescriptor / Detection）。

契约全文见《功能规格卡 v1.4》第 0.2 节；机器可校验版本由 photocheck-v4.schema.json 提供。
本模块把最容易违反的红线做成会抛异常的检查，而不是靠自觉：

1. 未知字段禁止（`from_dict` 严格模式）。
2. `evidence` 与 `kind` 固定对应，不接受手填。
3. `details` 的字段集合按 kind/subtype 严格限制；原始文字 / payload / EXIF 值禁止进入。
4. `meta` 的 `bbox` 必须为 null；其余必须有正宽高。
5. 同一 `image_id` 内 `id` 唯一；完整快照必须只有一个 ImageDescriptor。
6. `masked_preview` 按手机号/身份证使用固定掩码格式，任何归一化后长数字串都视为泄漏。
7. 二维码只允许 typed 的 `safe_domain` / `safe_ssid`，不再接受任意 `summary`。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

CONTRACT_VERSION = "photocheck/v4"

BBox = tuple[int, int, int, int]

# kind → 允许的 subtype（契约 v4 枚举，不得增删）
KIND_SUBTYPES: dict[str, tuple[str, ...]] = {
    "meta": ("gps", "datetime", "device", "serial", "thumbnail", "software"),
    "text": ("phone", "idcard"),
    "qr": (
        "qr_wechat_card",
        "qr_wechat_group",
        "qr_wechat_pay",
        "qr_alipay",
        "qr_wifi",
        "qr_vcard",
        "qr_contact",
        "qr_geo",
        "qr_code",
        "qr_link",
        "qr_unknown",
    ),
    "face": ("face_region",),
}

# evidence 与 kind 固定对应，由本模块派生，调用方不得传入
EVIDENCE_BY_KIND: dict[str, str] = {
    "meta": "exif",
    "text": "ocr_rule",
    "qr": "qr_payload",
    "face": "face_box",
}

_META_KEYS = frozenset({"masked_preview"})
_TEXT_PHONE_KEYS = frozenset({"masked_preview"})
_TEXT_IDCARD_KEYS = frozenset({"masked_preview", "idcard_check"})
_QR_KEYS = frozenset({"decodable", "safe_domain", "safe_ssid"})
_FACE_KEYS: frozenset[str] = frozenset()

# 只要出现就说明有人把明文塞进了可序列化记录
FORBIDDEN_DETAIL_KEYS = frozenset(
    {
        "text",
        "raw_text",
        "original",
        "payload",
        "raw_payload",
        "qr_payload",
        "raw_exif",
        "exif",
        "text_ref",
        "payload_ref",
        "summary",
        "value",
    }
)

IDCARD_CHECK_VALUES = ("pass", "fail", "na")

# 掩码里不该出现连续 8 位以上数字（手机号 11 位、身份证 18 位都远超这个阈值）
_UNSAFE_NORMALIZED_DIGITS = re.compile(r"\d{7,}")
_PHONE_MASK = re.compile(r"^(?:\+?86[\s-]?)?1[3-9]\d\*{4}\d{4}$")
_IDCARD_MASK = re.compile(r"^\d{4}\*{10}\d{4}$")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DOMAIN_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_SUMMARY_MAX_LEN = 64


class ContractError(ValueError):
    """违反 v4 契约。"""


def allowed_detail_keys(kind: str, subtype: str) -> frozenset[str]:
    if kind == "meta":
        return _META_KEYS
    if kind == "text":
        if subtype == "phone":
            return _TEXT_PHONE_KEYS
        if subtype == "idcard":
            return _TEXT_IDCARD_KEYS
    if kind == "qr":
        allowed = {"decodable"}
        if subtype == "qr_wifi":
            allowed.add("safe_ssid")
        elif subtype in {
            "qr_wechat_card",
            "qr_wechat_group",
            "qr_wechat_pay",
            "qr_alipay",
            "qr_geo",
            "qr_link",
        }:
            allowed.add("safe_domain")
        return frozenset(allowed)
    if kind == "face":
        return _FACE_KEYS
    raise ContractError(f"未知 kind/subtype: {kind}/{subtype}")


def required_detail_keys(kind: str, subtype: str) -> frozenset[str]:
    if kind == "text" and subtype == "idcard":
        return frozenset({"idcard_check"})
    if kind == "qr":
        return frozenset({"decodable"})
    return frozenset()


def _check_bbox(bbox: Any, kind: str, where: str) -> BBox | None:
    if kind == "meta":
        if bbox is not None:
            raise ContractError(f"{where}: kind=meta 的 bbox 必须为 null，得到 {bbox!r}")
        return None
    if bbox is None:
        raise ContractError(f"{where}: kind={kind} 的 bbox 不能为 null")
    if not isinstance(bbox, (tuple, list)) or len(bbox) != 4:
        raise ContractError(f"{where}: bbox 必须是 [x, y, width, height]，得到 {bbox!r}")
    vals = []
    for v in bbox:
        if isinstance(v, bool) or not isinstance(v, (int,)):
            raise ContractError(f"{where}: bbox 必须是整数坐标，得到 {bbox!r}")
        vals.append(int(v))
    x, y, w, h = vals
    if w <= 0 or h <= 0:
        raise ContractError(f"{where}: bbox 宽高必须为正，得到 {bbox!r}")
    if x < 0 or y < 0:
        raise ContractError(f"{where}: bbox 起点不能为负，得到 {bbox!r}")
    return (x, y, w, h)


def _check_details(kind: str, subtype: str, details: Any, where: str) -> dict[str, Any]:
    if details is None:
        details = {}
    if not isinstance(details, Mapping):
        raise ContractError(f"{where}: details 必须是对象，得到 {type(details).__name__}")

    keys = set(details)
    leaked = keys & FORBIDDEN_DETAIL_KEYS
    if leaked:
        raise ContractError(
            f"{where}: details 不得包含明文字段 {sorted(leaked)}（原始文字/payload/EXIF 只允许走 SecretStore）"
        )

    allowed = allowed_detail_keys(kind, subtype)
    unknown = keys - allowed
    if unknown:
        raise ContractError(f"{where}: {kind}/{subtype} 的 details 出现未知字段 {sorted(unknown)}，允许 {sorted(allowed)}")

    missing = required_detail_keys(kind, subtype) - keys
    if missing:
        raise ContractError(f"{where}: {kind}/{subtype} 的 details 缺少必填项 {sorted(missing)}")

    out: dict[str, Any] = {}
    for k, v in details.items():
        if k == "idcard_check":
            if v not in IDCARD_CHECK_VALUES:
                raise ContractError(f"{where}: idcard_check 只能是 {IDCARD_CHECK_VALUES}，得到 {v!r}")
        elif k == "decodable":
            if not isinstance(v, bool):
                raise ContractError(f"{where}: decodable 必须是布尔值，得到 {v!r}")
        elif k == "safe_domain":
            if not isinstance(v, str) or not v.strip():
                raise ContractError(f"{where}: safe_domain 必须是非空字符串，得到 {v!r}")
            out[k] = _normalize_domain(v, where)
            continue
        elif k == "safe_ssid":
            if not isinstance(v, str) or not v:
                raise ContractError(f"{where}: safe_ssid 必须是非空字符串，得到 {v!r}")
            if len(v) > _SUMMARY_MAX_LEN:
                raise ContractError(f"{where}: safe_ssid 超过 {_SUMMARY_MAX_LEN} 字符")
            if any(ord(char) < 32 for char in v):
                raise ContractError(f"{where}: safe_ssid 不得包含控制字符")
        elif k == "masked_preview":
            if not isinstance(v, str) or not v:
                raise ContractError(f"{where}: masked_preview 必须是非空字符串，得到 {v!r}")
            if len(v) > _SUMMARY_MAX_LEN:
                raise ContractError(f"{where}: masked_preview 超过 {_SUMMARY_MAX_LEN} 字符")
            if kind == "text" and subtype == "phone" and not _PHONE_MASK.fullmatch(v):
                raise ContractError(
                    f"{where}: 手机号 masked_preview 必须形如 138****8000，得到 {v!r}"
                )
            if kind == "text" and subtype == "idcard" and not _IDCARD_MASK.fullmatch(v):
                raise ContractError(
                    f"{where}: 身份证 masked_preview 必须形如 1101**********0011，得到 {v!r}"
                )
            normalized_digits = re.sub(r"[\s\-_./:+()]", "", v)
            if _UNSAFE_NORMALIZED_DIGITS.search(normalized_digits):
                raise ContractError(
                    f"{where}: masked_preview 归一化后仍含长数字串，疑似未掩码：{v!r}"
                )
        out[k] = v
    return out


def _normalize_domain(value: str, where: str) -> str:
    candidate = value.strip().rstrip(".").lower()
    if any(ord(char) < 32 or char.isspace() for char in candidate):
        raise ContractError(f"{where}: safe_domain 不得包含空白或控制字符")
    if any(char in candidate for char in "/\\@:;?#%&=+"):
        raise ContractError(f"{where}: safe_domain 只能是域名，不能包含协议、路径或参数")
    try:
        ascii_domain = candidate.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ContractError(f"{where}: safe_domain 不是合法域名：{value!r}") from exc
    labels = ascii_domain.split(".")
    if len(ascii_domain) > 253 or len(labels) < 2 or any(
        not _DOMAIN_LABEL.fullmatch(label) for label in labels
    ):
        raise ContractError(f"{where}: safe_domain 不是合法域名：{value!r}")
    return ascii_domain


@dataclass(frozen=True)
class Detection:
    """只读检测事实。不含用户选择、复检状态或原始敏感值。"""

    id: str
    image_id: str
    kind: str
    subtype: str
    bbox: BBox | None = None
    detector_score: float | None = None
    risk: int = 1
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _ID_PATTERN.fullmatch(self.id):
            raise ContractError(
                f"Detection.id 非法：{self.id!r}（只允许字母数字与 _.:-，长度 1-128）"
            )
        if not isinstance(self.image_id, str) or not _ID_PATTERN.fullmatch(self.image_id):
            raise ContractError("Detection.image_id 必须符合 v4 Identifier 规则")
        if self.kind not in KIND_SUBTYPES:
            raise ContractError(f"未知 kind：{self.kind!r}，允许 {sorted(KIND_SUBTYPES)}")
        if self.subtype not in KIND_SUBTYPES[self.kind]:
            raise ContractError(f"kind={self.kind} 不允许 subtype={self.subtype!r}")
        if isinstance(self.risk, bool) or self.risk not in (1, 2, 3):
            raise ContractError(f"risk 只能是 1/2/3，得到 {self.risk!r}")
        if self.detector_score is not None:
            if isinstance(self.detector_score, bool) or not isinstance(self.detector_score, (int, float)):
                raise ContractError(f"detector_score 必须是数字或 null，得到 {self.detector_score!r}")
            if not (0.0 <= float(self.detector_score) <= 1.0):
                raise ContractError(f"detector_score 必须在 0~1，得到 {self.detector_score!r}")

        object.__setattr__(self, "bbox", _check_bbox(self.bbox, self.kind, f"Detection({self.id}).bbox"))
        object.__setattr__(
            self,
            "details",
            _check_details(self.kind, self.subtype, self.details, f"Detection({self.id}).details"),
        )
        if self.detector_score is not None:
            object.__setattr__(self, "detector_score", float(self.detector_score))

    @property
    def evidence(self) -> str:
        return EVIDENCE_BY_KIND[self.kind]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "record_type": "Detection",
            "id": self.id,
            "image_id": self.image_id,
            "kind": self.kind,
            "subtype": self.subtype,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "detector_score": self.detector_score,
            "evidence": self.evidence,
            "risk": self.risk,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Detection":
        expected = {
            "contract_version",
            "record_type",
            "id",
            "image_id",
            "kind",
            "subtype",
            "bbox",
            "detector_score",
            "evidence",
            "risk",
            "details",
        }
        unknown = set(data) - expected
        if unknown:
            raise ContractError(f"Detection 出现未知字段 {sorted(unknown)}")
        missing = expected - set(data)
        if missing:
            raise ContractError(f"Detection 缺少字段 {sorted(missing)}")
        if data["contract_version"] != CONTRACT_VERSION:
            raise ContractError(f"contract_version 必须为 {CONTRACT_VERSION}，得到 {data['contract_version']!r}")
        if data["record_type"] != "Detection":
            raise ContractError(f"record_type 必须为 Detection，得到 {data['record_type']!r}")
        kind = data["kind"]
        if kind in EVIDENCE_BY_KIND and data["evidence"] != EVIDENCE_BY_KIND[kind]:
            raise ContractError(
                f"evidence 与 kind 不匹配：kind={kind} 必须是 {EVIDENCE_BY_KIND[kind]}，得到 {data['evidence']!r}"
            )
        bbox = data["bbox"]
        return cls(
            id=data["id"],
            image_id=data["image_id"],
            kind=kind,
            subtype=data["subtype"],
            bbox=bbox,
            detector_score=data["detector_score"],
            risk=data["risk"],
            details=data["details"] or {},
        )


@dataclass(frozen=True)
class ImageDescriptor:
    """描述规范化工作图。

    字段定义以 B 的 K-01 与 photocheck-v4.schema.json 为准，本类只做最小校验，
    目的是让 A 在没有 B 的模块时也能自测。
    """

    image_id: str
    width: int
    height: int
    orientation: str = "exif_transposed"
    coordinate_space: str = "top_left_pixels"

    def __post_init__(self) -> None:
        if not isinstance(self.image_id, str) or not _ID_PATTERN.fullmatch(self.image_id):
            raise ContractError("ImageDescriptor.image_id 必须符合 v4 Identifier 规则")
        if isinstance(self.width, bool) or not isinstance(self.width, int) or self.width <= 0:
            raise ContractError(f"ImageDescriptor.width 必须为正整数，得到 {self.width!r}")
        if isinstance(self.height, bool) or not isinstance(self.height, int) or self.height <= 0:
            raise ContractError(f"ImageDescriptor.height 必须为正整数，得到 {self.height!r}")
        if self.coordinate_space != "top_left_pixels":
            raise ContractError(f"coordinate_space 固定为 top_left_pixels，得到 {self.coordinate_space!r}")
        if self.orientation != "exif_transposed":
            raise ContractError(
                f"orientation 固定为 exif_transposed，得到 {self.orientation!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "record_type": "ImageDescriptor",
            "image_id": self.image_id,
            "width": self.width,
            "height": self.height,
            "orientation": self.orientation,
            "coordinate_space": self.coordinate_space,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ImageDescriptor":
        expected = {
            "contract_version",
            "record_type",
            "image_id",
            "width",
            "height",
            "orientation",
            "coordinate_space",
        }
        unknown = set(data) - expected
        if unknown:
            raise ContractError(f"ImageDescriptor 出现未知字段 {sorted(unknown)}")
        missing = expected - set(data)
        if missing:
            raise ContractError(f"ImageDescriptor 缺少字段 {sorted(missing)}")
        if data["contract_version"] != CONTRACT_VERSION:
            raise ContractError(
                f"contract_version 必须为 {CONTRACT_VERSION}，得到 {data['contract_version']!r}"
            )
        if data["record_type"] != "ImageDescriptor":
            raise ContractError(
                f"record_type 必须为 ImageDescriptor，得到 {data['record_type']!r}"
            )
        return cls(
            image_id=data["image_id"],
            width=data["width"],
            height=data["height"],
            orientation=data["orientation"],
            coordinate_space=data["coordinate_space"],
        )


def validate_records(records: Iterable[Mapping[str, Any]]) -> None:
    """校验完整 v4 快照；也兼容仅包含 Detection 的调用。"""
    records = list(records)
    descriptors: list[ImageDescriptor] = []
    detections: list[Detection] = []
    seen: dict[str, set[str]] = {}
    for i, rec in enumerate(records):
        rec_type = rec.get("record_type")
        if rec_type == "Detection":
            detections.append(Detection.from_dict(rec))
        elif rec_type == "ImageDescriptor":
            descriptors.append(ImageDescriptor.from_dict(rec))
        else:
            raise ContractError(
                f"records[{i}] 不是 Detection 或 ImageDescriptor（record_type={rec_type!r}）"
            )
    if len(descriptors) > 1:
        raise ContractError("一个校验快照最多只能包含一个 ImageDescriptor")
    expected_image_id = descriptors[0].image_id if descriptors else None
    for det in detections:
        if expected_image_id is not None and det.image_id != expected_image_id:
            raise ContractError(
                f"Detection.image_id={det.image_id} 与 ImageDescriptor 不一致"
            )
        bucket = seen.setdefault(det.image_id, set())
        if det.id in bucket:
            raise ContractError(f"image_id={det.image_id} 内 id 重复：{det.id}")
        bucket.add(det.id)


__all__ = [
    "CONTRACT_VERSION",
    "BBox",
    "KIND_SUBTYPES",
    "EVIDENCE_BY_KIND",
    "IDCARD_CHECK_VALUES",
    "FORBIDDEN_DETAIL_KEYS",
    "ContractError",
    "Detection",
    "ImageDescriptor",
    "allowed_detail_keys",
    "required_detail_keys",
    "validate_records",
]
