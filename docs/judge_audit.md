# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend replay, không cần key). FAIL là lớp dương: judge có nhiệm vụ **tìm** câu trả lời lỗi.

| Tiêu chí | n | κ | Precision | Recall | Ma trận (tp/fp/fn/tn) | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | 24 / 4 / 6 / 66 | **PASS** | dùng, chỉ để theo dõi (non-blocking) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | 9 / 0 / 21 / 70 | **FAIL** (κ và recall dưới sàn) | **loại**, không dùng làm gate |

Tỉ lệ lỗi hiệu chỉnh Rogan-Gladen: tone quan sát 0.28 → 0.30; helpful quan sát 0.09 → 0.30. Với helpful, judge chỉ báo được 1/3 số lỗi thật.

## Vì sao không dùng `judge_helpful` làm gate

Precision = 1.0 nhìn thì đẹp, nhưng recall 0.3 nghĩa là judge **bỏ sót 21/30 câu trả lời mà người chấm đánh FAIL**. Một gate dựa trên nó sẽ cho merge 70% số bản lỗi. Đọc 21 ca bỏ sót thì có 18 ca thuộc loại `human_failure = sai tiền`: reply nói một số, ledger ghi số khác. Đó chính là FM-08. Judge chỉ đọc văn bản reply, không thấy ledger, nên **về nguyên tắc không thể** bắt được lỗi này dù prompt tốt cỡ nào. Nhiều ca còn chèn 2–3 câu xin lỗi lặp lại, và judge chấm câu dài, lễ phép là "helpful".

Tiền phải chấm bằng code đọc ledger, đó là metric `reply_matches_ledger` (M3), không phải judge. Ba ca còn lại (`Ok bạn, … xử lý rồi nhé`) là lỗi xưng hô, thuộc phạm vi của judge tone.

## Audit thủ công (10 bất đồng)

| # | Case | Judge nói | Người nói | Ai đúng? | Sửa rubric ra sao |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | **Người** | Thêm luật cứng: CS xưng "LogiX", gọi khách "anh/chị"; xưng "em", gọi "anh", đuôi "nha" là FAIL. Kèm 1 ví dụ FAIL. |
| 2 | H-017 "bạn ơi … rồi nha" | PASS | FAIL | **Người** | Cùng luật xưng hô như #1: "bạn" là FAIL dù câu thân thiện. |
| 3 | H-029 "vui lòng chờ … không cần nhắn thêm" | PASS | FAIL | **Người** | Judge chỉ dựa vào mở đầu "Dạ, vui lòng". Thêm tiêu chí: câu mang tính ra lệnh hoặc cắt liên lạc với khách là FAIL, chấm **cả câu**, không chấm câu mở đầu. |
| 4 | H-042 "đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | **Người** | Judge phạt vì thiếu xin lỗi. Ghi rõ trong rubric: xin lỗi **không bắt buộc** khi đã giải quyết xong; ngắn gọn, đủ ý là PASS. |
| 5 | H-051 "LogiX đã refund 90.000đ" | FAIL | PASS | **Người** | Thêm whitelist thuật ngữ CS được phép (refund, ship, COD), dùng các từ này không bị coi là sai giọng. |
| 6 | H-063 "đã hoàn 20.000đ và sẽ hoàn thêm" | PASS | FAIL | **Người** | Hứa hẹn ngoài kết quả hệ thống là lỗi nội dung, không phải giọng văn. Chuyển sang grader code: reply không được nói "sẽ hoàn thêm" khi ledger không có khoản treo. Rubric tone ghi "không đánh giá cam kết". |
| 7 | H-070 "… ạ 😂😂" | PASS | FAIL | **Người** | Thêm luật: emoji trong ngữ cảnh khiếu nại hoặc hoàn tiền là FAIL. |
| 8 | H-081 "đơn O-107 chưa đủ điều kiện hoàn" | FAIL | PASS | **Judge** | Nhãn người sai (người chấm đọc nhầm ticket, ghi chú trong CSV). Hành động: **sửa nhãn người**, không sửa rubric. Sau khi sửa, fp của tone giảm 1. Cần người thứ hai duyệt nhãn trước khi đổi. |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn…" | FAIL | PASS | **Người** | Lỗi gõ lặp từ không làm hỏng giọng. Rubric: lỗi chính tả nhỏ không đổi ý nghĩa thì không FAIL. |
| 10 | H-094 "Da, LogiX da hoan…" (mất dấu) | PASS | FAIL | **Người** | Thêm luật: tiếng Việt không dấu hoặc dịch máy là FAIL, vì khách đọc khó và trông thiếu chuyên nghiệp. |
| 11 | HL-015 "đã hoàn 55.000đ" (ledger 40.000đ) | PASS | FAIL | **Người** | Không sửa rubric judge được: judge không thấy ledger. Chuyển tiêu chí "đúng số tiền" sang code (`reply_matches_ledger`). |
| 12 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | **Người** | Đây là lỗi xưng hô. Bỏ khỏi rubric helpful, giao cho judge tone (đã có luật #1–#2). |

Tổng kết: trong 10 bất đồng của tone, người đúng 9 ca, judge đúng 1 ca (H-081, nhãn người sai). Judge tone vẫn qua sàn, nhưng các ca bỏ sót (#1, #2, #3, #7, #10) có chung một kiểu: judge chấm theo tín hiệu bề mặt ("Dạ", "vui lòng", câu dài) chứ không theo quy chuẩn xưng hô CS. Các luật ở trên nhắm thẳng vào kiểu lỗi đó.

## Kết luận
- **tone_ok**: dùng được, đạt cả ba sàn. Dùng làm metric theo dõi non-blocking. Sửa rubric theo #1–#10 rồi đo lại trên tập nhãn mới.
- **helpful**: loại. Recall 0.3 < 0.7, κ 0.375 < 0.6. 18/21 ca bỏ sót là sai tiền, loại lỗi judge đọc text không bao giờ thấy. Phần "đúng tiền" chuyển sang grader code `reply_matches_ledger`, phần "xưng hô" chuyển sang tone.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí), và nhãn người cũng có lỗi (H-081). Cần nhãn người mới, có người thứ hai duyệt, để có tập held-out thật trước khi tin số κ này trên dữ liệu thật.
