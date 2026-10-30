# Antigravity Multi-CLI Hub

> Hệ thống quản lý tài khoản / cookie Antigravity độc lập và trình khởi chạy CLI đa Terminal (Profile Isolation).  
> Cho phép chạy đồng thời nhiều tài khoản Google khác nhau trên cùng một máy, mỗi Terminal mang một danh tính riêng biệt.

---

## 🌟 Tính Năng Chính

1. **Giao diện Web Trực Quan (`app.py`)**:
   - Thêm tài khoản Google 1-click qua chuẩn **Google OAuth 2.0 PKCE** an toàn.
   - Hỗ trợ dán trực tiếp Refresh Token / Cookie có sẵn.
   - Tự động nhận diện Email và phân hạng (`Ultra` / `Pro`).
   - Tự động sinh thư mục Profile cách ly `profiles/<mã_tài_khoản>`.
   - Nút **"Mở Terminal"** 1-click (tự mở cửa sổ Terminal mới trên macOS).
   - Kiểm tra kết nối và hạn ngạch (Health Check) trực tiếp trên Web.

2. **Trình Chạy Terminal Độc Lập (`run.py` / `run.sh`)**:
   - Mỗi Terminal chạy với một `$HOME` giả lập riêng, không bao giờ xung đột hay đá phiên nhau.
   - Nhận diện mã tài khoản: `python3 run.py acc-1`, `python3 run.py acc-2`.
   - Hỗ trợ chế độ tương tác (Interactive Subshell) hoặc chạy lệnh đơn lẻ:
     ```bash
     python3 run.py acc-1 agy -p "Vẽ bức tranh bìa sách"
     ```

3. **Cầu Nối Hermes & Zalo Bot (`hermes_bridge.py`)**:
   - Tự động nhận diện danh tính từng Terminal: `account_id`, `email`, `pid`, `hostname`.
   - Gửi sự kiện thời gian thực (Terminal mở, lệnh hoàn thành, lỗi quota 429) tới máy chủ Hermes và Zalo Bot.
   - Tài liệu kỹ thuật chi tiết để mang sang máy khác code tiếp: [`HERMES_ZALO_GUIDE.md`](./HERMES_ZALO_GUIDE.md).

---

## 🚀 Hướng Dẫn Sử Dụng

### 1. Khởi động Web App quản lý

Chạy lệnh sau:
```bash
./start.sh
```
*(hoặc: `python3 app.py`)*

Trình duyệt sẽ tự động mở trang quản trị tại: `http://localhost:7890`

### 2. Thêm tài khoản Google / Antigravity
1. Trên giao diện Web, bấm nút **"Thêm Tài Khoản"**.
2. Nhập mã tài khoản muốn đặt (ví dụ: `acc-1`, `ultra-1`).
3. Bấm nút **"Mở Đăng Nhập Google (OAuth PKCE)"**.
4. Cửa sổ Google mở lên ➔ Chọn Gmail của bạn ➔ Bấm **Cho phép**.
5. Copy mã xác thực Google trả về ➔ Dán vào ô và bấm **Khởi Tạo Profile & CLI**.

### 3. Mở Terminal theo từng tài khoản

#### Cách A: Bấm nút trên Web UI
Trên từng thẻ tài khoản, bấm nút **"Mở Terminal"** ➔ Một cửa sổ macOS Terminal mới sẽ tự động bật lên và kích hoạt sẵn tài khoản đó!

#### Cách B: Mở thủ công từ bất kỳ Terminal nào
- Vào tài khoản 1:
  ```bash
  python3 run.py acc-1
  ```
- Mở thêm một tab / cửa sổ Terminal khác và vào tài khoản 2:
  ```bash
  python3 run.py acc-2
  ```
- Hoặc gõ lệnh trực tiếp:
  ```bash
  python3 run.py acc-1 agy -p "Vẽ chú mèo phi hành gia" --output-format json
  ```

---

## 📁 Cấu Trúc Thư Mục

```text
antigravity-multi-cli/
├── app.py                # Web App Dashboard (Zero-dependency Python HTTP Server)
├── run.py                # Terminal Runner (Cơ chế cách ly $HOME & token auto-refresh)
├── run.sh                # Lệnh tắt chạy CLI
├── start.sh              # Lệnh tắt khởi động Web App
├── hermes_bridge.py      # Module gửi sự kiện tới Hermes & Zalo Bot
├── hermes_config.json    # Cấu hình kết nối Hermes / Zalo
├── HERMES_ZALO_GUIDE.md  # Tài liệu kỹ thuật chuyển giao máy kia để code Hermes
├── README.md             # Hướng dẫn sử dụng tổng quát
├── data/
│   ├── accounts.json     # Danh sách tài khoản đã nạp
│   └── events.log        # Lịch sử sự kiện Terminal
└── profiles/             # Các thư mục Profile độc lập
    ├── acc-1/
    │   └── .gemini/antigravity-cli/antigravity-oauth-token
    └── acc-2/
        └── .gemini/antigravity-cli/antigravity-oauth-token
```

---

## 📡 Chuyển Giao Sang Máy Khác (Hermes & Zalo)
Xem tài liệu chi tiết tại file [`HERMES_ZALO_GUIDE.md`](./HERMES_ZALO_GUIDE.md).
File này chứa đầy đủ:
- Sơ đồ kiến trúc Mermaid
- Đặc tả JSON Payload
- Code mẫu FastAPI Listener cho máy Hermes
- Hướng dẫn chuyển tiếp tin nhắn vào Zalo Bot (cá nhân hoặc OA)
