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

## Giao diện Tkinter (bản thử nghiệm)

```powershell
python ui.py
```

UI mở trình duyệt Playwright riêng như CLI. Bấm **Khởi chạy**, đăng nhập/chuyển đúng shop trên trình duyệt rồi bấm **Đã đăng nhập — Tiếp tục** trong UI. Không chạy đồng thời CLI và UI vì cùng dùng `user_data/`.

Ô **Link Google Sheet** là tùy chọn: để trống sẽ lấy `SPREADSHEET_URL` trong `config.py`; nhập URL khác thì chỉ dùng cho lượt chạy đó, không ghi đè config. Dùng link dạng `https://docs.google.com/spreadsheets/d/<ID>/edit` (có thể kèm query/gid). Link sai định dạng sẽ được cảnh báo trước khi chạy; ô nhập được khóa trong lượt chạy và mở lại khi kết thúc. Sheet vẫn cần đúng các tab/cột của mẫu hiện tại và được cấp quyền cho service account trong `credentials.json`; URL đúng định dạng không đảm bảo quyền truy cập hoặc nội dung hợp lệ.

Checkpoint vẫn có tên theo ngày/shop/SKU nhưng lưu thêm ID Sheet nguồn. Nếu chọn Sheet khác, script chặn khôi phục để tránh dùng danh sách hoặc ghi kết quả nhầm nguồn. Checkpoint cũ chưa có ID nguồn cần đối chiếu và nhập `DUNG NGUON` một lần trước khi tiếp tục; không chắc thì để trống để dừng. Đổi query/gid trên link của cùng một Sheet không đổi nguồn.

- Khung log nhận toàn bộ stdout/stderr của lượt chạy, có màu lỗi/cảnh báo, thanh cuộn ngang/dọc và sao chép vùng chọn. Chỉ giữ 10.000 dòng gần nhất trên màn hình; file log vẫn lưu đầy đủ. Cuộn lên xem log cũ sẽ tắt tự cuộn; bật lại **Tự cuộn** để theo dõi cuối log. **Xóa màn hình** không xóa file log.
- Các câu hỏi y/n chuyển thành nút, các xác nhận `DA GUI DU`, `CHUA CHIA SE` và URL có ô nhập riêng. Không tự điền hoặc tự đồng ý xác nhận gửi. Để trống/không tiếp tục giữ ý nghĩa như CLI.
- **Dừng an toàn** yêu cầu dừng ở điểm kiểm tra tiếp theo hoặc khi đang chờ phản hồi. Không ngắt giữa lệnh gửi/chờ kết quả; có thể phải chờ timeout hiện tại. Giữ checkpoint và trình duyệt mở để kiểm tra. Nếu đã thao tác gửi mà chưa rõ kết quả, chạy lại vẫn bị chặn như CLI.
- **Khởi chạy** lần nữa đọc nguồn Sheet mới và tái sử dụng phiên trình duyệt trên cùng luồng; có thể đăng nhập/chuyển shop tại bước chờ đăng nhập. Khi đóng UI, ứng dụng hỏi trước, chờ dừng an toàn rồi đóng phiên trình duyệt trên luồng sở hữu nó. Cookie và checkpoint vẫn giữ lại.
- Dùng **Mở thư mục log** để mở `outputs/logs/`. Nếu khởi động thiếu thư viện hoặc bước nào lỗi, xem khung log; CLI vẫn chạy độc lập bằng `python app.py`.

Xem thử UI mà không kết nối TikTok/Sheet:

```powershell
python ui.py --demo
```

Luồng DEMO nằm trong `test/demo/ui_demo.py`, chỉ được nạp khi chạy `--demo`. Thư mục `test/` được Git bỏ qua theo yêu cầu, nên DEMO chỉ dùng cục bộ khi có thư mục này; giao diện thật không phụ thuộc thư mục test. DEMO chỉ in dữ liệu giả và thử các bước xác nhận; không mở trình duyệt thật, không ghi Sheet/checkpoint hay gửi lời mời/tin nhắn. DEMO vẫn tạo file log. Tkinter thường có sẵn trong bộ cài Python Windows; nếu `import tkinter` lỗi, bổ sung thành phần Tcl/Tk từ bộ cài Python. Chưa đóng gói EXE.

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
| `interaction.py` | Prompt và điểm dừng hợp tác dùng chung CLI/UI |
| `ui_runtime.py` | Luồng sở hữu Playwright, hàng đợi log/context/prompt |
| `ui.py` | Cửa sổ Tkinter |
| `test/demo/ui_demo.py` | Luồng DEMO ngoại tuyến, chỉ dùng cục bộ |

## Hành vi đang giữ nguyên

- Keyword Việt, Anh từ Sheet, brand và các biến thể hiện có; có giới hạn dừng khi không có kết quả mới. Chưa triển khai vòng quét 100/200 creator hoặc quét vô hạn tới đủ DAILY.
- Chỉ tạo lời mời khi đủ mục tiêu còn thiếu, chia tối đa 50 creator/đợt. Đặt bảng 50/trang rồi chọn checkbox tổng trên cùng trang.
- Các tiêu chí followers, GMV, số món và cách loại trùng không thay đổi. Module rules tách ra không sửa cách parse hoặc các trường hợp biên hiện có.
- LIST LƯU TẠM là nguồn Sheet duy nhất để chống trùng creator; người vừa lưu được bổ sung ngay vào tập chống trùng của lượt chạy. Creator không đạt tiêu chí chỉ lưu lý do loại trong checkpoint. Creator chờ gửi được khôi phục từ checkpoint dù đã lưu Sheet. Không cần tab BLACK LIST.
- Checkpoint cũ có bản ghi loại theo quy tắc chống trùng trước đây sẽ được mở lại keyword tương ứng để kiểm tra lại riêng những creator đó theo LIST LƯU TẠM; giữ nguyên danh sách đã chọn và lịch sử gửi.
- Chat vẫn dùng bước xác nhận của người vận hành. Script chỉ cuộn bảng người nhận trong popup và đọc username/checkbox, không click checkbox. Đối chiếu đủ người và bộ đếm trước Chia sẻ; người chưa tích nhưng còn khả dụng sẽ làm dừng để kiểm tra.
- Người chưa tích và bị khóa được lưu vào `chat_result.rate_limit_usernames` của đợt trong checkpoint. Sau xác nhận chat, follow-up = số creator thực tế trong đợt trừ số bị khóa. Đây là số theo lựa chọn và xác nhận người dùng, chưa phải xác minh độc lập từng tin nhắn. Mọi người bị khóa thì không bấm Chia sẻ, ghi 0.
- Tab `THEO DÕI LỜI MỜI` cần các tiêu đề duy nhất: `TÊN LỜI MỜI`, `FOLLOW-UP ĐÃ GỬI`, `NGÀY FOLLOW-UP`, `RATE LIMIT TIN NHẮN CREATOR`. Script cập nhật ba cột cuối theo tên tiêu đề trên duy nhất dòng lời mời, ghi username ngăn cách `/` và ngày UTC+7; giữ các cột khác. Kết quả chat được lưu checkpoint trước khi ghi Sheet; lỗi ghi Sheet vẫn giữ đợt chưa hoàn tất để đối chiếu, không tự gửi lại.
- Sheet chỉ cache đối tượng tab để tránh lấy metadata lặp lại. Nội dung hàng/cột vẫn đọc mới; cách ghi từng creator và thứ tự lưu checkpoint giữ nguyên. Nếu đổi tên/xóa/tạo lại tab trong lúc chạy, khởi động lại hoặc gọi `clear_worksheet_cache()`.

## Checkpoint và debug

Giữ `outputs/checkpoints/` khi chạy lại. Checkpoint tách theo ngày/shop/SKU; ngày mới tự dùng file mới. Creator chờ gửi được khôi phục. Đợt lỗi trước gửi ở `draft` có thể cấu hình lại; `sending` hoặc đã thao tác Chia sẻ nhưng chưa xác nhận vẫn bị chặn để tránh gửi trùng.

Đợt `sent` ở bước `chat` có thể tiếp tục riêng chat nếu checkpoint ghi `chat_result.share_clicked=false`. URL chat được lưu trước câu hỏi y/n; chạy lại mở đúng URL có `plan_id` và `shop_id`, kiểm tra đúng shop và đối chiếu danh sách creator. Không tạo lại lời mời hay ghi thêm dòng lịch sử. Nếu chat đã `confirmed=true` nhưng ghi Sheet lỗi, chỉ thử lại cập nhật Sheet. Phục hồi này chạy trước kiểm tra DAILY đã đủ và trước bước cần keyword.

Checkpoint cũ chưa có trạng thái chat cần người vận hành nhập `CHUA CHIA SE` chỉ khi chắc chắn chưa bấm Chia sẻ; nếu thiếu URL thì dán URL chat của đúng lời mời từ TikTok. Không chắc kết quả thì nhấn Enter để dừng. Không đổi `sent` về `draft` hoặc xóa checkpoint. Ctrl+C trước Chia sẻ giữ trạng thái chưa gửi; Ctrl+C sau thao tác Chia sẻ giữ dấu đã thao tác và không tự gửi lại. Nhánh này chỉ xử lý checkpoint ngày hiện tại, chưa tự đối chiếu ngày trước.

Mỗi lần chạy ghi log riêng trong `outputs/logs/`, có shop, SKU, đợt, bước, keyword và creator khi có. Lỗi trình duyệt cố lưu ảnh, DOM liên quan và metadata vào `outputs/debug/`. Việc thu bằng chứng thất bại không thay thế lỗi gốc.

`credentials.json`, `user_data/`, checkpoint, log, ảnh/DOM debug và `test/` được Git bỏ qua. Log và DOM có thể chứa dữ liệu creator/shop; chỉ chia sẻ phần cần thiết sau khi kiểm tra nội dung.

## Kiểm tra cục bộ

Các file `test/` chỉ giữ trên máy theo yêu cầu, không đưa lên Git. Với thư mục này còn trên máy:

```powershell
python -m unittest discover -s test -t . -p "test_*.py"
```

Test dùng mock và HTML cục bộ, không đăng nhập TikTok, không ghi Sheet hoặc gửi lời mời. Test DOM chạy Chrome đã cài ở đường dẫn mặc định Windows, hoặc Chromium của Playwright; có thể đặt `AT_TEST_CHROME` thành đường dẫn Chrome khác. Nếu không có trình duyệt chạy được, nhóm DOM sẽ báo skip. Test so sánh trace thao tác cũ/mới để phát hiện thay đổi luồng do refactor.
