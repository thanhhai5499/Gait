import { AlertTriangle } from 'lucide-react'

/**
 * Hộp thoại xác nhận dùng chung — thay cho window.confirm của trình duyệt.
 *
 * @param {boolean}  open        Hiển thị dialog hay không
 * @param {string}   title       Tiêu đề
 * @param {string}   message     Nội dung mô tả
 * @param {string}   confirmText Nhãn nút xác nhận
 * @param {string}   cancelText  Nhãn nút hủy
 * @param {boolean}  loading     Đang xử lý (disable nút)
 * @param {boolean}  danger      Tô đỏ nút xác nhận (hành động phá hủy)
 * @param {() => void} onConfirm Callback khi bấm xác nhận
 * @param {() => void} onCancel  Callback khi đóng / hủy
 */
export default function ConfirmDialog({
  open,
  title = 'Xác nhận',
  message,
  confirmText = 'Xác nhận',
  cancelText = 'Hủy',
  loading = false,
  danger = true,
  onConfirm,
  onCancel,
}) {
  if (!open) return null

  const confirmCls = danger
    ? 'bg-red-600 hover:bg-red-700'
    : 'bg-blue-600 hover:bg-blue-700'

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={onCancel}
    >
      <div
        className="bg-white rounded-2xl w-full max-w-sm p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 mb-4">
          {danger && (
            <div className="shrink-0 w-10 h-10 rounded-full bg-red-100 flex items-center justify-center">
              <AlertTriangle size={20} className="text-red-600" />
            </div>
          )}
          <div>
            <h3 className="text-lg font-semibold text-gray-800">{title}</h3>
            {message && <p className="text-sm text-gray-600 mt-1 leading-relaxed">{message}</p>}
          </div>
        </div>
        <div className="flex gap-3">
          <button
            onClick={onCancel}
            disabled={loading}
            className="flex-1 border border-gray-300 py-2.5 rounded-lg hover:bg-gray-50 disabled:opacity-50"
          >
            {cancelText}
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className={`flex-1 text-white py-2.5 rounded-lg font-medium disabled:opacity-50 ${confirmCls}`}
          >
            {loading ? 'Đang xử lý...' : confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}
