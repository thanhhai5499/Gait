"""
Đọc giá trị baseline ban đầu khi đứng im.

Chạy:
    cd d:\Aiot\Gait\BE
    .\venv\Scripts\python.exe read_baseline.py

Yêu cầu: Tắt BE trước khi chạy. Cắm CH340 và đứng im trong 5 giây.
"""
import time
import sys
import serial
from app.services.serial_reader import auto_detect_ch340

BAUD_RATE = 115200
DURATION_S = 5  # Đọc trong 5 giây


def read_baseline():
    # 1. Detect CH340
    result = auto_detect_ch340()
    if not result:
        print("❌ Không tìm thấy CH340. Cắm thiết bị rồi thử lại.")
        sys.exit(1)

    port = result["port"]
    print(f"✅ CH340 detected: {port}")
    print(f"⏳ Đứng im trong {DURATION_S} giây...\n")

    # 2. Mở serial
    conn = serial.Serial(port, BAUD_RATE, timeout=2)
    time.sleep(2)  # Chờ Arduino reset
    conn.reset_input_buffer()

    # 3. Đọc dữ liệu
    field_names = [
        "left_hip", "left_knee", "right_hip", "right_knee",
        "left_force_1", "left_force_2", "right_force_1", "right_force_2",
        "accel_x", "accel_y", "accel_z",
        "gyro_x", "gyro_y", "gyro_z",
        "magn_x", "magn_y", "magn_z",
    ]
    data = {name: [] for name in field_names}
    count = 0
    start = time.time()

    while (time.time() - start) < DURATION_S:
        raw = conn.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="ignore").strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(",")
        if len(parts) < 18:
            continue

        for i, name in enumerate(field_names):
            val = parts[i + 1].strip()  # Skip timestamp at [0]
            try:
                data[name].append(float(val))
            except ValueError:
                pass
        count += 1

    conn.close()
    elapsed = time.time() - start

    if count == 0:
        print("❌ Không nhận được dữ liệu.")
        sys.exit(1)

    # 4. Tính toán và in kết quả
    print(f"📊 Đã đọc {count} mẫu trong {elapsed:.1f}s ({count/elapsed:.0f} Hz)\n")
    print("=" * 72)
    print(f"{'Field':<16} {'Mean':>10} {'Min':>10} {'Max':>10} {'Std':>8}  Đánh giá")
    print("-" * 72)

    for name in field_names:
        vals = data[name]
        if not vals:
            print(f"{name:<16} {'N/A':>10}")
            continue

        mean = sum(vals) / len(vals)
        mn = min(vals)
        mx = max(vals)
        std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5

        # Đánh giá
        status = ""
        if name in ("left_hip", "left_knee", "right_hip", "right_knee"):
            # Góc: kỳ vọng ~0° hoặc ~360°
            if mean > 350 or mean < 10:
                status = "✅ OK (~0°)"
            else:
                status = f"⚠️ Lệch {mean:.1f}°"
        elif name.startswith("left_force") or name.startswith("right_force"):
            # FSR: kỳ vọng ~0
            if mean < 50:
                status = "✅ OK"
            else:
                status = f"⚠️ Có tải ({mean:.0f})"
        elif name.startswith("accel"):
            # Accel: 1 trục phải ~9.81 hoặc ~1.0
            if abs(mean) > 8:
                status = "✅ Gravity detected (m/s²)"
            elif abs(mean) > 0.8 and abs(mean) < 1.2:
                status = "✅ Gravity detected (g)"
            elif abs(mean) < 0.5:
                status = "✅ OK (không phải trục gravity)"
            else:
                status = "⚠️ Kiểm tra đơn vị"
        elif name.startswith("gyro"):
            # Gyro: kỳ vọng ~0
            if abs(mean) < 2:
                status = "✅ OK"
            else:
                status = f"❌ Offset = {mean:.2f} → cần calibrate"
        elif name.startswith("magn"):
            # Magn: ổn định là được
            if std < 5:
                status = "✅ Ổn định"
            else:
                status = "⚠️ Nhiễu cao"

        print(f"{name:<16} {mean:>10.2f} {mn:>10.2f} {mx:>10.2f} {std:>8.3f}  {status}")

    print("=" * 72)
    print("\n💡 Ghi chú:")
    print("   - Góc: 358-360° hoặc 0-2° đều là bình thường (= đứng thẳng)")
    print("   - FSR: 0 khi chân không chạm đất, >300 khi đứng")
    print("   - Gyro: PHẢI < ±2 deg/s khi nghỉ. Nếu lớn → cần offset calibration")
    print("   - Accel: PHẢI thấy ~9.81 (m/s²) hoặc ~1.0 (g) trên 1 trục")


if __name__ == "__main__":
    read_baseline()
