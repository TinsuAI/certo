from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.web.templating import templates

router = APIRouter()

# Read-only component gallery for the 2026-08-20 UI redesign. Renders every
# component of the design system on one page with sample content so the system
# can be judged in one screen. No client, no case, no store access — the route
# is a pure template render and must stay that way.

# kind: "color" → paint a swatch chip; "text" → show the resolved value only.
TOKEN_GROUPS = [
    {
        "id": "surface",
        "title": "Bề mặt",
        "note": "Nền trang, thẻ và các lớp chìm/nổi. Không dùng cho chữ hay viền.",
        "tokens": [
            ("--background", "color"),
            ("--background-top", "color"),
            ("--background-accent", "color"),
            ("--background-accent-2", "color"),
            ("--card", "color"),
            ("--card-muted", "color"),
            ("--menu-surface", "color"),
            ("--surface-subtle", "color"),
            ("--surface-hover", "color"),
            ("--surface-sunk", "color"),
            ("--surface-overlay", "color"),
            ("--surface-input", "color"),
        ],
    },
    {
        "id": "text",
        "title": "Chữ",
        "note": "Ba mức đậm nhạt cho chữ; --stale dành riêng cho dữ liệu đã cũ.",
        "tokens": [
            ("--foreground", "color"),
            ("--foreground-soft", "color"),
            ("--foreground-muted", "color"),
            ("--stale", "color"),
        ],
    },
    {
        "id": "border",
        "title": "Viền",
        "note": "--border cho đường phân cách, --border-strong cho ô nhập và viền cần thấy rõ.",
        "tokens": [
            ("--border", "color"),
            ("--border-strong", "color"),
            ("--muted-bd", "color"),
            ("--success-bd", "color"),
            ("--warning-bd", "color"),
            ("--critical-bd", "color"),
            ("--info-bd", "color"),
        ],
    },
    {
        "id": "action",
        "title": "Hành động",
        "note": "Màu của link, nút chính và trạng thái đang chọn — giống nhau ở cả CO và Data Hub.",
        "tokens": [
            ("--primary", "color"),
            ("--primary-hover", "color"),
            ("--primary-soft", "color"),
            ("--primary-foreground", "color"),
        ],
    },
    {
        "id": "semantic",
        "title": "Ngữ nghĩa",
        "note": "Chỉ dùng khi màu mang nghĩa: đạt, cảnh báo, lỗi, thông tin. Không dùng để trang trí.",
        "tokens": [
            ("--success", "color"),
            ("--success-soft", "color"),
            ("--warning", "color"),
            ("--warning-soft", "color"),
            ("--error", "color"),
            ("--error-soft", "color"),
            ("--info", "color"),
            ("--info-soft", "color"),
        ],
    },
    {
        "id": "navy",
        "title": "Dải xanh hải quân — mặt dữ liệu",
        "note": "Chrome ứng dụng: header, hàng sidebar đang mở, hover/chọn dòng bảng. Đây là màu của DỮ LIỆU.",
        "tokens": [
            ("--brand-50", "color"),
            ("--brand-100", "color"),
            ("--brand-200", "color"),
            ("--brand-500", "color"),
            ("--brand-600", "color"),
            ("--brand-700", "color"),
        ],
    },
    {
        "id": "logic",
        "title": "Dải chàm — mặt logic",
        "note": "Bảng quyết định, biểu thức, vết chạy máy luật. Đây là màu của LOGIC — không trộn với dải hải quân.",
        "tokens": [
            ("--logic-50", "color"),
            ("--logic-100", "color"),
            ("--logic-200", "color"),
            ("--logic-500", "color"),
            ("--logic-600", "color"),
            ("--logic-700", "color"),
        ],
    },
    {
        "id": "identity",
        "title": "Nhận diện ứng dụng",
        "note": "Chỉ cho monogram và vạch nhận diện. CO là mặt tính toán nên --brand là chàm; Data Hub là hải quân.",
        "tokens": [
            ("--brand", "color"),
            ("--brand-foreground", "color"),
        ],
    },
    {
        "id": "shape",
        "title": "Bóng và hình khối",
        "note": "Một bóng nhẹ cho thẻ, một bóng sâu cho lớp phủ. Bo góc nhỏ dần theo kích thước phần tử.",
        "tokens": [
            ("--shadow-md", "text"),
            ("--shadow-lg", "text"),
            ("--radius-sm", "text"),
            ("--radius-md", "text"),
            ("--radius-lg", "text"),
            ("--radius-xl", "text"),
            ("--radius-pill", "text"),
            ("--header-h", "text"),
            ("--side-w", "text"),
        ],
    },
]

TYPE_STEPS = [
    ("--fs-2xl", "1.4rem", "Tiêu đề trang (h1)"),
    ("--fs-xl", "1.25rem", "Tiêu đề khối lớn"),
    ("--fs-lg", "1.05rem", "Tiêu đề thẻ"),
    ("--fs-md", "0.875rem", "Chữ thân bài"),
    ("--fs-sm", "0.8125rem", "Chú thích, ô nhập"),
    ("--fs-xs", "0.72rem", "Nhãn, badge, tiêu đề cột"),
]

# Sample figures for the tabular-numerics demonstration. Real shape of a bảng kê
# money column: mixed widths, mixed decimals, one negative.
NUMERIC_SAMPLE = [
    ("Khung nhôm định hình 6063-T5", "1.284.500.000", "12.845,50"),
    ("Tôn mạ kẽm dày 0,5 mm", "98.320.400", "983,20"),
    ("Bo mạch điều khiển MPPT", "7.410.925.300", "74.109,25"),
    ("Ốc vít inox M6×20", "412.000", "4,12"),
    ("Chênh lệch điều chỉnh kỳ trước", "-15.600.750", "-156,01"),
]

RAIL_STEPS = [
    ("1", "Lô hàng", "done"),
    ("2", "Chứng từ", "done"),
    ("3", "Bảng kê C/O", "on"),
    ("4", "TKX / TKN", ""),
    ("5", "Review & Xuất", ""),
]

SECTIONS = [
    ("tokens", "Màu"),
    ("type", "Chữ"),
    ("buttons", "Nút"),
    ("badges", "Nhãn"),
    ("tables", "Bảng"),
    ("forms", "Biểu mẫu"),
    ("surfaces", "Thẻ, ô số, ghi chú, rỗng, đường ống"),
    ("overlays", "Hộp thoại và toast"),
]


@router.get("/design", response_class=HTMLResponse)
async def design_gallery(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="design_gallery.html",
        context={
            "token_groups": TOKEN_GROUPS,
            "type_steps": TYPE_STEPS,
            "numeric_sample": NUMERIC_SAMPLE,
            "rail_steps": RAIL_STEPS,
            "sections": SECTIONS,
        },
    )
