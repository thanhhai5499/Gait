// Chân Trái: warm — Hip=đỏ, Knee=cam, Ankle=vàng
// Chân Phải: cool — Hip=xanh dương, Knee=tím, Ankle=xanh lá
export const COLORS = ['#dc2626', '#ea580c', '#ca8a04', '#2563eb', '#7c3aed', '#059669']
export const COLORS2 = ['#2563eb', '#dc2626']

// Map theo TÊN series từ backend (không phụ thuộc thứ tự/index) để tránh gán nhãn sai.
// Backend gửi: "Left Hip", "Left Knee", "Right Hip", "Right Knee".
export const SERIES_META = {
  'Left Hip':    { label: 'Hông Trái',    color: '#dc2626' },
  'Left Knee':   { label: 'Gối Trái',     color: '#ea580c' },
  'Left Ankle':  { label: 'Cổ chân Trái', color: '#ca8a04' },
  'Right Hip':   { label: 'Hông Phải',    color: '#2563eb' },
  'Right Knee':  { label: 'Gối Phải',     color: '#7c3aed' },
  'Right Ankle': { label: 'Cổ chân Phải', color: '#059669' },
}
export const seriesLabel = (name) => SERIES_META[name]?.label ?? name
export const seriesColor = (name, i) => SERIES_META[name]?.color ?? COLORS[i % COLORS.length]
