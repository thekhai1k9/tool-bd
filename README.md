# TikTok Shop creator automation

Chạy một shop mỗi lần, lấy tiêu chí và mục tiêu DAILY riêng cho từng SKU từ Google Sheets. Refactor này giữ nguyên chính sách tìm kiếm, gửi lời mời, xác nhận chat và checkpoint hiện có.

## Cài đặt và chạy

Dùng Python 3.12 trên Windows, tại thư mục dự án:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
python app.py
```

Đặt khóa service account tại `credentials.json` và cấp quyền Sheet cho tài khoản đó. URL Sheet và trang tìm creator nằm trong `config.py`; mặc định giữ nguyên URL trước refactor. Đăng nhập đúng shop trên trình duyệt được mở và làm theo hướng dẫn console.

## Cấu trúc code

| File | Trách nhiệm |
| --- | --- |
| `app.py` | Khởi động, đọc nguồn, đăng nhập, gọi workflow |
| `workflow.py` | Xử lý SKU, thu thập creator, điều phối từng đợt |
| `browser_helper.py` | Thao tác TikTok, các bước cấu hình/gửi lời mời và chat |
| `creator_rules.py` | Chuẩn hóa username, parse số và kiểm tra tiêu chí thuần Python |
| `sheet_helper.py` | Đọc/ghi Google Sheets; giữ API các hàm kiểm tra cũ |
| `search_progress.py` | Keyword mở rộng và checkpoint theo ngày/shop/SKU |
| `diagnostics.py` | Log theo lần chạy, context và bằng chứng khi lỗi |
| `config.py` | Cấu hình kết nối hiện có |

## Hành vi đang giữ nguyên

- Keyword Việt, Anh từ Sheet, brand và các biến thể hiện có; có giới hạn dừng khi không có kết quả mới. Chưa triển khai vòng quét 100/200 creator hoặc quét vô hạn tới đủ DAILY.
- Chỉ tạo lời mời khi đủ mục tiêu còn thiếu, chia tối đa 50 creator/đợt. Đặt bảng 50/trang rồi chọn checkbox tổng trên cùng trang.
- Các tiêu chí followers, GMV, số món và cách loại trùng không thay đổi. Module rules tách ra không sửa cách parse hoặc các trường hợp biên hiện có.
- LIST LƯU TẠM là nguồn Sheet duy nhất để chống trùng creator; người vừa lưu được bổ sung ngay vào tập chống trùng của lượt chạy. Creator không đạt tiêu chí chỉ lưu lý do loại trong checkpoint. Creator chờ gửi được khôi phục từ checkpoint dù đã lưu Sheet. Không cần tab BLACK LIST.
- Checkpoint cũ có bản ghi loại theo quy tắc chống trùng trước đây sẽ được mở lại keyword tương ứng để kiểm tra lại riêng những creator đó theo LIST LƯU TẠM; giữ nguyên danh sách đã chọn và lịch sử gửi.
- Chat vẫn dùng bước xác nhận của người vận hành. Follow-up vẫn được gán bằng số creator đã mời sau xác nhận, chưa phải số đo độc lập từ chat.
- Sheet chỉ cache đối tượng tab để tránh lấy metadata lặp lại. Nội dung hàng/cột vẫn đọc mới; cách ghi từng creator và thứ tự lưu checkpoint giữ nguyên. Nếu đổi tên/xóa/tạo lại tab trong lúc chạy, khởi động lại hoặc gọi `clear_worksheet_cache()`.

## Checkpoint và debug

Giữ `outputs/checkpoints/` khi chạy lại. Checkpoint tách theo ngày/shop/SKU; ngày mới tự dùng file mới. Creator chờ gửi được khôi phục. Đợt lỗi trước gửi ở `draft` có thể cấu hình lại; trạng thái `sending`, `sent` chưa hoàn tất hoặc chưa rõ kết quả phải kiểm tra lịch sử/chat trước khi chạy lại để tránh gửi trùng.

Mỗi lần chạy ghi log riêng trong `outputs/logs/`, có shop, SKU, đợt, bước, keyword và creator khi có. Lỗi trình duyệt cố lưu ảnh, DOM liên quan và metadata vào `outputs/debug/`. Việc thu bằng chứng thất bại không thay thế lỗi gốc.

`credentials.json`, `user_data/`, checkpoint, log, ảnh/DOM debug và `test/` được Git bỏ qua. Log và DOM có thể chứa dữ liệu creator/shop; chỉ chia sẻ phần cần thiết sau khi kiểm tra nội dung.

## Kiểm tra cục bộ

Các file `test/` chỉ giữ trên máy theo yêu cầu, không đưa lên Git. Với thư mục này còn trên máy:

```powershell
python -m unittest discover -s test -t . -p "test_*.py"
```

Test dùng mock và HTML cục bộ, không đăng nhập TikTok, không ghi Sheet hoặc gửi lời mời. Test DOM chạy Chrome đã cài ở đường dẫn mặc định Windows, hoặc Chromium của Playwright; có thể đặt `AT_TEST_CHROME` thành đường dẫn Chrome khác. Nếu không có trình duyệt chạy được, nhóm DOM sẽ báo skip. Test so sánh trace thao tác cũ/mới để phát hiện thay đổi luồng do refactor.
