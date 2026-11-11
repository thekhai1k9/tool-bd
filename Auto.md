## 1. Phạm vi

- Shop: ....
- Shop ID: ....
- Tài khoản thao tác: tài khoản đã được người dùng đăng nhập sẵn.
- Không lưu hoặc yêu cầu mật khẩu.

## 2. Nguồn dữ liệu bắt buộc

Đọc phiên bản mới nhất trước mỗi yêu cầu trong file `INFO - BOOKING KOL/KOC-AUTO (link file google sheet)`:

1. `CMS SKU`: SKU, ngành hàng chính, commission, followers, GMV và số món bán.
2. `LIST KEYWORD`: keyword, ngành hàng, brand cùng ngành/cùng công dụng và biến thể tìm kiếm.
3. `INFO SẢN PHẨM`: thông tin sản phẩm, cách dùng và nội dung phù hợp chính sách.
4. `NỘI DUNG LỜI MỜI`: mẫu lời mời theo sản phẩm.
5. `TIN NHẮN FOLLOW UP`: mẫu tin nhắn sau lời mời.
6. `THEO DÕI LỜI MỜI`: lịch sử lời mời đã gửi.
7. `LIST LƯU TẠM`: danh sách creator đã lọc để đối chiếu trùng cho các yêu cầu sau.

Đọc file blacklist `LIST BOOKING KOL/KOC (link file google sheet)` trước khi chọn creator.

## 3. Lọc creator

1. Vào `Khám phá các nhà sáng tạo` → `Tìm nhà sáng tạo`.
2. Lọc theo đúng CMS SKU: ngành hàng chính, hạng mục con, followers, GMV/số món và chất lượng nội dung.
3. Tìm lần lượt toàn bộ keyword trong `LIST KEYWORD`; mở rộng sang brand, biến thể tiếng Việt/Anh và các trang kết quả tiếp theo.
4. Scroll liên tục để tải thêm kết quả, không chỉ dùng trang đầu.
5. Loại creator có trong blacklist, sai ngành hàng/tệp khán giả, nội dung sơ sài hoặc không đạt điều kiện.
6. Chỉ chọn creator mới. Loại creator trong blacklist, danh sách đã hợp tác, danh sách đã gửi hoặc LIST LƯU TẠM có trước đợt hiện tại, không phụ thuộc SKU. Nhãn `Đã mời trước đây` phải đối chiếu lịch sử; nếu không xác minh được là creator mới thì không chọn.
7. Lưu danh sách tạm vào `LIST LƯU TẠM (link google sheet- có thể lưu ra 1 link file google sheet khác)`. Không xóa dữ liệu sau khi hoàn tất; dùng làm nguồn đối chiếu trùng cho các lần sau.

## 4. Tạo lời mời mới

1. Vào `Cộng tác` → `Cộng tác mục tiêu`.
2. Bấm `Mời cộng tác` để tạo lời mời mới; không mở/chỉnh sửa lời mời cũ.
3. Tên: `BD_AUTO_[4 số đuôi ID SKU]-[NGÀY/THÁNG]`.
4. Hiệu lực: 30 ngày kể từ ngày gửi.
5. Zalo: số liên hệ đã được người dùng cấu hình.
6. Nội dung: lấy từ `NỘI DUNG LỜI MỜI (link google sheet)`; commission phải theo `CMS SKU`.
7. Loại nội dung ưu tiên: `Không có ưu tiên`.
8. Sản phẩm: chọn đúng SKU.
9. Hàng mẫu: bật `Cung cấp hàng mẫu miễn phí` và chọn `Sử dụng cài đặt hàng mẫu cấp sản phẩm`; tuyệt đối không chọn `Phê duyệt mọi người trong lời mời này`.

## 5. Thêm creator vào lời mời

1. Trong `Chọn nhà sáng tạo`, tìm từng username/ID từ `LIST LƯU TẠM (link google sheet)`.
2. Bấm tìm kiếm, chọn đúng creator và tick checkbox.
3. Không bấm `Thêm nhà sáng tạo đã chọn trước`.
4. Đủ số lượng mục tiêu mới tiến hành gửi.
5. Nếu TikTok báo trùng, chọn `Xóa nhà sáng tạo khỏi lời mời này`; không chỉnh sửa lời mời cũ.

## 6. Gửi và follow-up

- Trước nút `Gửi`, phải kiểm tra lại số creator, SKU, commission, expiry, mẫu miễn phí và không có cảnh báo trùng.
- Hệ thống vẫn yêu cầu xác nhận ngay trước thao tác gửi lời mời ra ngoài.
- Sau khi gửi thành công, mở `Cooperation Chat`, chọn các creator khả dụng thuộc lời mời vừa gửi và dùng mẫu trong `TIN NHẮN FOLLOW UP (link google sheet)`.
- Hệ thống vẫn yêu cầu xác nhận ngay trước thao tác gửi follow-up.
- Không gửi cho creator bị loại hoặc không nằm trong lời mời vừa gửi.

## 7. Cập nhật sau khi hoàn tất

1. Ghi vào `THEO DÕI LỜI MỜI (link google sheet- có thể lưu ra 1 link file google sheet khác)`: STT, tên lời mời, số creator thực tế gửi thành công, ngày gửi và ngày hết hạn.
2. Export bằng bản sao riêng của `outputs/report/shopped_MAU.xlsx`, lưu trong thư mục outputs của dự án. Chỉ xóa dữ liệu cũ trong bản sao báo cáo mới; giữ mẫu và báo cáo lịch sử.
3. Mỗi sản phẩm/ngày gửi tạo một sheet theo cấu trúc `[Tên sản phẩm]_Ngày-Tháng`.
4. Giữ `LIST LƯU TẠM (link google sheet)` để làm dữ liệu đối chiếu trùng cho những lần sau.


## 9. Quy ước bổ sung theo yêu cầu mới nhất

- Mẫu cố định: Mẫu là bản sao file người dùng đính kèm; không sửa mẫu gốc.
- Mỗi ngày tạo file riêng SHOPPED_EXPORT_DD-MM-YYYY.xlsx từ mẫu. Trong BẢN SAO mới, xóa các hàng dữ liệu ngày cũ, giữ tiêu đề, định dạng và cấu trúc 9 cột. Tạo sheet từng sản phẩm theo [Tên sản phẩm]_Ngày-Tháng; không giữ các sheet dữ liệu lịch sử trong báo cáo ngày mới. Không xóa báo cáo lưu trữ hoặc danh sách chống trùng.
- Mục tiêu 250 LƯỢT MỜI/ngày: TM 100, DC 50, XK 100, chia 5 đợt x 50 theo kết quả đã thống nhất. Báo riêng số KOC duy nhất. Một KOC phù hợp nhiều sản phẩm có thể nhận các SKU khác nhau; số dòng SKU không phải số lượt mời.
- Trước mỗi ngày đọc nguồn mới nhất trong INFO - BOOKING KOL/KOC và blacklist LIST BOOKING KOL/KOC. Đối chiếu cả KOC đã hợp tác, LIST LƯU TẠM và lịch sử gửi cục bộ. Chỉ lấy KOC mới so với danh sách có sẵn; cùng ngày có thể phân bổ KOC đã chọn sang nhiều SKU phù hợp. Không mời lặp cùng KOC–SKU đang có lời mời hoạt động.
- Dùng số liệu/ngành hàng và bằng chứng nội dung đã lưu trên trang kết quả nếu đủ đánh giá; không mở hồ sơ lặp không cần thiết. Chỗ thiếu bằng chứng phải ghi rõ, không tự nhận đã xác minh.
- Mỗi KOC thao tác cách nhau ít nhất 5 giây để trang tải; đây không phải bảo đảm không có CAPTCHA. Tick checkbox ngay khi KOC đạt tiêu chí và tiếp tục tới đủ số lượng.
- Lưu username/ID, SKU phù hợp, tiêu chí đã kiểm tra, lý do loại, keyword, trang/vị trí đã duyệt và số đếm sau từng nhóm. Tiếp tục từ checkpoint; không quét lại dữ liệu đã lưu.
- Nếu hồ sơ không truy cập được, đánh dấu chưa kiểm tra và bỏ khỏi danh sách được duyệt. Không giải hoặc vượt CAPTCHA. Nếu xác minh chặn cả phiên, lưu checkpoint và chờ người dùng hoàn tất xác minh; không đổi phiên để né kiểm soát.
- Có thể đóng tab công việc không còn dùng sau khi lưu trạng thái; giữ tab có bản nháp chưa lưu hoặc cần bàn giao.
- Trước gửi: đủ 250 lượt đủ điều kiện, đối chiếu trùng, đúng SKU, commission từ CMS SKU mới nhất, hạn 30 ngày, mẫu miễn phí cấp sản phẩm, thông tin liên hệ và nội dung. Báo tổng số lượt, KOC duy nhất, số đợt, SKU và điều kiện để người dùng duyệt. Chỉ gửi khi người dùng xác nhận cho đợt cụ thể; không dùng phê duyệt ngày trước cho ngày mới.
- Sau gửi xác minh số thực tế thành công rồi cập nhật THEO DÕI LỜI MỜI và báo cáo. Follow-up chỉ gửi cho người nhận khả dụng của lời mời vừa gửi, dùng mẫu mới nhất và có phê duyệt riêng.
- Nếu thao tác gửi bị treo, trạng thái là chưa xác nhận; kiểm tra lịch sử trước khi gửi lại. Không tính bản nháp là đã gửi và không tự gửi lại đợt trạng thái chưa rõ.
- Tự động chạy hàng ngày CHƯA được cấu hình: phiên hiện tại không có công cụ lịch chạy có thể truy cập Chrome cục bộ. Quy trình đã lưu là hướng dẫn tiếp tục khi phiên được mở, không phải lịch tự chạy.

## 11. Chống trùng — yêu cầu mới nhất

Chỉ cập nhật creator mới chưa có trong danh sách đã gửi hoặc LIST LƯU TẠM, không phụ thuộc SKU. Chuẩn hóa username: trim, bỏ @ đầu, so sánh không phân biệt hoa/thường; dùng creator ID ổn định nếu có. Một KOC mới được chọn trong cùng đợt có thể phân bổ nhiều SKU phù hợp, nhưng không tính đó là KOC mới thứ hai. Lưu kết quả mới theo ngày; giữ nguyên lịch sử, không xóa creator cũ khỏi dữ liệu đối chiếu.

## 12. Luồng vận hành hàng ngày đã thống nhất

1. Đọc SOP, checkpoint của đợt trước và nguồn dữ liệu mới nhất. Ghi nhận kết quả thực tế của đợt trước; nếu chưa đủ hoặc còn thao tác gửi không rõ kết quả, tiếp tục xử lý hoặc báo người dùng, không âm thầm bỏ qua.
2. Tạo danh sách loại trừ từ blacklist, creator đã hợp tác, lịch sử gửi và LIST LƯU TẠM có trước đợt mới. Giữ bản danh sách loại trừ lúc bắt đầu đợt để creator vừa lưu trong chính đợt đó không bị coi nhầm là creator cũ. Chống trùng nội bộ trong từng danh sách chọn.
3. Lọc từ danh sách kết quả theo CMS SKU và keyword; không mở chi tiết hồ sơ creator. Chỉ sử dụng bằng chứng đủ rõ trên trang kết quả hoặc đã lưu; nếu thiếu điều kiện bắt buộc, bỏ qua và ghi lý do.
4. Chờ khoảng 5 giây mỗi KOC hoặc lâu hơn nếu trang chưa tải xong. Khoảng chờ giúp thao tác có trật tự, không bảo đảm tránh CAPTCHA. Khi CAPTCHA chặn thao tác, lưu trạng thái và báo cần xác minh thủ công.
5. Creator phù hợp thì tick checkbox đầu dòng ngay; tiếp tục từng creator đến TM 100, XK 100, DC 50. Lưu mỗi lượt quét vào LIST LƯU TẠM và checkpoint cục bộ theo ngày/đợt, gồm ID, username, nhóm sản phẩm, bằng chứng, keyword, vị trí tiếp tục và số lượng. Không quét lại phần đã lưu.
6. Khi đủ 250 lượt hợp lệ, kiểm tra cấu hình lời mời, đối chiếu trùng và báo người dùng duyệt trước gửi. Ghi riêng số creator duy nhất và số lượt/SKU; không tính bản nháp hoặc SKU phụ là lời mời gửi thành công.
7. Sau khi duyệt, gửi, kiểm tra kết quả, follow-up theo mẫu cho đúng người nhận khả dụng và theo phạm vi phê duyệt. Không dùng phê duyệt đợt cũ cho đợt mới.
8. Cập nhật THEO DÕI LỜI MỜI, lưu lịch sử chống trùng và xuất báo cáo ngày theo mẫu trong thư mục đã chỉ định. Mỗi trạng thái chưa xác nhận phải ghi rõ; kiểm tra trước khi gửi lại.
9. Giữ các tab/phiên đã đăng nhập cần thiết và lịch sử công việc; chỉ đóng tab công việc thừa sau khi đã lưu. Không đăng xuất, xóa cookie hoặc sao chép thông tin xác thực. Không thể bảo đảm phiên trình duyệt luôn kết nối hoặc tự đồng bộ đăng nhập giữa các thiết bị/nền tảng. Dùng cùng tài khoản và mở lại cuộc trò chuyện/SOP để tiếp tục; nếu phiên hết hạn, người dùng đăng nhập lại.
10. Tần suất mong muốn: hàng ngày, sau khi kiểm tra trạng thái đợt trước. Khi có phiên chạy được hỗ trợ, chuẩn bị đủ mục tiêu rồi báo duyệt gửi. Hiện chưa thiết lập lịch tự chạy Chrome cục bộ; không tuyên bố lịch đang hoạt động. Khi không thể chạy hoặc thiếu số lượng, báo tình trạng và số còn thiếu.


## 14. Tối ưu quét và xử lý lỗi — cập nhật 08/10/2026

Áp dụng yêu cầu mới nhất: tự quyết định các bước vận hành đã được giao; không hỏi lại keyword, thứ tự nhóm, retry thông thường hoặc cách lưu. Tiếp tục công việc tới kết quả có thể duyệt. Không kết thúc chỉ vì đã thêm một vài hồ sơ. Khi không thể tiếp tục, báo trở ngại thực tế, các cách hợp lệ đã thử, số thiếu và điểm tiếp tục; không tuyên bố tự chạy nền hoặc đã đủ chỉ tiêu.