# Project Status

## Current State
- Repo vẫn ở pha discovery cho bài toán C/O; chưa có application stack hay implementation plan chốt cuối.
- Hiện đã có thêm bằng chứng trực tiếp từ source VBA của workbook chính, không chỉ suy luận từ sheet/formula. Source đã được export vào `.ai/extracted-vba/tru-lui-co-final-2025-commercial-mac/`.
- `docs/BUSINESS_LOGIC_CONFIRMATION.md` đã được chỉnh tiếp theo hướng agency-facing hơn: giải thích rõ hơn các lớp nghiệp vụ, bỏ cách nói kiểu "phía agency", sửa `5.1.2`, và chuyển ý về `nguồn mua nội địa` khỏi phần khẳng định dữ liệu đầu vào sang phần câu hỏi xác nhận.
- `docs/workbook-business-logic-foundation.md` đã được bổ sung các finding xác nhận trực tiếp từ VBA về flow vận hành và các rủi ro/migration constraints.

## Recent Changes
- Exported VBA modules từ workbook `tru lui CO final  SXXK - 2025 commercial-MAC - Huyền đúng.xlsm` vào `.ai/extracted-vba/tru-lui-co-final-2025-commercial-mac/`, kèm `README.md` và `manifest.json`.
- Xác nhận bằng code rằng workbook là một stateful allocation/ledger engine với flow chính `NK -> NK2 -> DM/Xuat -> X-N -> Save -> Tru lui`, có generator `RunUpgrade` cho `LVC`, `RVC`, `CTH`, `CTSH`, `EUR1`, và có macro export/in chứng từ hỗ trợ.
- Ghi thêm vào `docs/workbook-business-logic-foundation.md` các điểm đã được VBA xác nhận trực tiếp: MAC-address gate, hardcoded sheet password, run key `DM!K6`, external path dependency, legacy/new macro coexistence, expiry checks, và các brittleness trong macro cũ.
- Tiếp tục tinh chỉnh `docs/BUSINESS_LOGIC_CONFIRMATION.md` ở các phần `1.1.3`, `1.1.4`, `5.1.2`, `5.2`, `5.3` để mô tả đúng workbook hiện tại và tránh khẳng định quá mức về `nguồn mua nội địa`.

## Next Steps
- Review lại `docs/BUSINESS_LOGIC_CONFIRMATION.md` với người dùng/đơn vị vận hành để chốt các mục mở, đặc biệt quanh `DM`, `Save`, `Tru lui`, chứng từ đầu vào mua trong nước, và cách chọn rule/form/agreement.
- Dùng source VBA đã export để tiếp tục map field-level semantics của các sheet trọng yếu (`DM`, `X-N`, `Save`, `Tru lui`) thành mô hình nghiệp vụ rõ hơn trong `docs/`.
- Quyết định lô thay đổi project files nào sẽ được commit cùng nhau; hiện nhiều docs và report vẫn đang ở trạng thái chưa commit.

## Blockers
- Chưa có xác nhận từ operator/agency cho một số semantics quan trọng trong workbook, nên nhiều kết luận vẫn ở mức "evidence-backed hypothesis" chứ chưa phải rule nghiệp vụ cuối cùng.
- Repo đang có nhiều thay đổi project files chưa commit ngoài handoff artifacts.

## Notes for Next AI Session
- Người dùng muốn câu chữ tiếng Việt gọn, trực diện, không dùng kiểu diễn đạt như `phía agency`.
- Không được đánh đồng `quy tắc xuất xứ`, `hiệp định áp dụng`, `loại mẫu C/O`, và `kênh cấp / kênh nộp`.
- Từ code VBA đã xác nhận được: workbook không tự "thử mọi rule rồi chọn rule tốt nhất"; operator chạy macro/sheet theo rule mục tiêu.
- `HS code` trong workbook được dùng như thuộc tính phân loại/rule input, không phải khóa định danh vận hành chính; product/material đang bám nhiều hơn vào `mã SP/model` và `mã NVL`.
- Ngoài repo, đã chỉnh `~/.codex/config.toml` để status line ưu tiên hiện số (`used-tokens`, `context-remaining`, `context-window-size`) thay vì bar-only `context-used`.
