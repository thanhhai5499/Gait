# Giá trị baseline kỳ vọng — 18 fields khi thiết bị ở trạng thái nghỉ
# ===========================================================================
# Dùng file này để calibrate firmware trước khi gửi dữ liệu vào hệ thống.
# Hệ thống parse theo thứ tự cố định 18 fields, phân cách bằng dấu phẩy.
#
# Format: timestamp,f1,f2,...,f17
# ===========================================================================

## THỨ TỰ VÀ GIÁ TRỊ KỲ VỌNG KHI NGHỈ (không ai đi)

| Index | Field         | Đơn vị     | Baseline kỳ vọng | Ghi chú                              |
|-------|---------------|------------|-------------------|--------------------------------------|
| 0     | timestamp_ms  | ms         | Tăng dần          | millis() từ Arduino, reset mỗi lần bật |
| 1     | left_hip      | degree     | 0 ± 2°            | Flexion dương, extension âm. Nghỉ = 0° |
| 2     | left_knee     | degree     | 0 ± 2°            | Flexion dương. Nghỉ = 0° (đứng thẳng) |
| 3     | right_hip     | degree     | 0 ± 2°            | Giống left_hip                        |
| 4     | right_knee    | degree     | 0 ± 2°            | Giống left_knee                       |
| 5     | left_force_1  | ADC 0-1023 | 0                 | FSR mũi chân trái. 0 = không chạm đất |
| 6     | left_force_2  | ADC 0-1023 | 0                 | FSR gót chân trái. 0 = không chạm đất |
| 7     | right_force_1 | ADC 0-1023 | 0                 | FSR mũi chân phải                    |
| 8     | right_force_2 | ADC 0-1023 | 0                 | FSR gót chân phải                     |
| 9     | accel_x       | m/s²       | 0 ± 0.5           | Phụ thuộc hướng đặt IMU              |
| 10    | accel_y       | m/s²       | 0 ± 0.5           | Phụ thuộc hướng đặt IMU              |
| 11    | accel_z       | m/s²       | ±9.81             | Trục thẳng đứng = trọng lực          |
| 12    | gyro_x        | deg/s      | 0 ± 1             | PHẢI gần 0 khi nghỉ                  |
| 13    | gyro_y        | deg/s      | 0 ± 1             | PHẢI gần 0 khi nghỉ                  |
| 14    | gyro_z        | deg/s      | 0 ± 1             | PHẢI gần 0 khi nghỉ                  |
| 15    | magn_x        | µT         | Tuỳ địa phương    | Ổn định, không nhảy                   |
| 16    | magn_y        | µT         | Tuỳ địa phương    | Ổn định, không nhảy                   |
| 17    | magn_z        | µT         | Tuỳ địa phương    | Ổn định, không nhảy                   |


## GIÁ TRỊ THỰC TẾ ĐO ĐƯỢC TỪ THIẾT BỊ (chưa calibrate)

Dòng mẫu: 760,358.94,359.30,359.30,358.94,0,0,0,0,0.20,-1.20,-0.40,42.74,3.72,14.21,31.50,-177.30,-3.90

| Index | Field         | Thực tế    | Kỳ vọng   | Trạng thái  |
|-------|---------------|------------|------------|-------------|
| 0     | timestamp_ms  | 760        | Tăng dần   | ✅ OK       |
| 1     | left_hip      | 358.94°    | ~0°        | ⚠️ Cần convert: gửi 0° thay vì 359° |
| 2     | left_knee     | 359.30°    | ~0°        | ⚠️ Cần convert                      |
| 3     | right_hip     | 359.30°    | ~0°        | ⚠️ Cần convert                      |
| 4     | right_knee    | 358.94°    | ~0°        | ⚠️ Cần convert                      |
| 5     | left_force_1  | 0          | 0          | ✅ OK       |
| 6     | left_force_2  | 0          | 0          | ✅ OK       |
| 7     | right_force_1 | 0          | 0          | ✅ OK       |
| 8     | right_force_2 | 0          | 0          | ✅ OK       |
| 9     | accel_x       | 0.20       | 0 ± 0.5   | ⚠️ Không thấy gravity — kiểm tra đơn vị |
| 10    | accel_y       | -1.20      | 0 ± 0.5   | ⚠️ Có thể đang gửi g (không phải m/s²) |
| 11    | accel_z       | -0.40      | ±9.81      | ❌ Thiếu gravity — cần scale/convert |
| 12    | gyro_x        | 42.74      | 0 ± 1     | ❌ Offset lớn — cần calibrate        |
| 13    | gyro_y        | 3.72       | 0 ± 1     | ❌ Có offset                         |
| 14    | gyro_z        | 14.21      | 0 ± 1     | ❌ Offset lớn — cần calibrate        |
| 15    | magn_x        | 31.50      | Tuỳ        | ✅ OK (ổn định)                      |
| 16    | magn_y        | -177.30    | Tuỳ        | ✅ OK (ổn định)                      |
| 17    | magn_z        | -3.90      | Tuỳ        | ✅ OK (ổn định)                      |


## HƯỚNG DẪN CHỈNH FIRMWARE (ĐÃ ÁP DỤNG)

### 1. Góc khớp (index 1-4)
- Hiện gửi 0°-360°. Hệ thống chấp nhận cả hai convention.
- NẾU muốn chuẩn lâm sàng (flexion dương, extension âm):
  ```cpp
  float angle = readEncoder();
  if (angle > 180.0) angle -= 360.0;  // 359° → -1°
  ```
- HOẶC giữ 0-360° — BE sẽ tự convert khi phân tích.

### 2. Accelerometer (index 9-11)
- Phải thấy trọng lực trên 1 trục (~9.81 m/s² hoặc ~1.0 g)
- Nếu dùng MPU6050 raw: chia cho sensitivity (16384 cho ±2g range)
  ```cpp
  float accel_x = raw_ax / 16384.0 * 9.81;  // Đơn vị m/s²
  ```
- Hoặc gửi đơn vị g (chia 16384 không nhân 9.81) — ghi rõ trong docs

### 3. Gyroscope (index 12-14) — CẦN FIX
- Đọc 200 mẫu lúc khởi động, tính trung bình → lưu làm offset
  ```cpp
  // Trong setup():
  float gyro_offset[3] = {0, 0, 0};
  for (int i = 0; i < 200; i++) {
      readIMU();
      gyro_offset[0] += raw_gx;
      gyro_offset[1] += raw_gy;
      gyro_offset[2] += raw_gz;
      delay(5);
  }
  gyro_offset[0] /= 200.0;
  gyro_offset[1] /= 200.0;
  gyro_offset[2] /= 200.0;

  // Trong loop():
  float gyro_x = (raw_gx - gyro_offset[0]) / 131.0;  // deg/s (±250 range)
  ```

### 4. FSR (index 5-8) — OK, không cần chỉnh

### 5. Magnetometer (index 15-17) — OK, không cần chỉnh
- Giá trị phụ thuộc hướng từ trường địa phương, chỉ cần ổn định.


## KHI ĐI BỘ — GIÁ TRỊ KỲ VỌNG

| Field         | Khoảng bình thường khi đi     |
|---------------|-------------------------------|
| Hip           | -10° (extension) đến +30° (flexion) |
| Knee          | 0° (đứng thẳng) đến +60° (flexion) |
| FSR           | 0 (swing) → 300-800 (stance)  |
| Accel (pelvis)| Dao động ±3 m/s² quanh gravity |
| Gyro          | Dao động ±100 deg/s           |
| Magn          | Ổn định ± nhiễu nhẹ           |
