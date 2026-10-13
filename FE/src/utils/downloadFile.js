// Tải tệp từ response dạng blob của axios về máy người dùng.

const FILENAME_RE = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i

/** Đọc tên tệp từ header Content-Disposition; trả fallback nếu header vắng hoặc sai định dạng. */
export function filenameFromResponse(response, fallback) {
  const header = response?.headers?.['content-disposition']
  const match = header ? FILENAME_RE.exec(header) : null
  if (!match) return fallback
  const raw = match[1].trim()
  try {
    return decodeURIComponent(raw)
  } catch {
    return raw
  }
}

/** Kích hoạt trình duyệt tải blob về với tên tệp cho trước. */
export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  // Thu hồi trễ: một số trình duyệt hủy tải nếu URL bị revoke ngay sau click.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Với responseType 'blob', body lỗi cũng là Blob nên phải đọc ra mới lấy được `detail`. */
export async function errorMessageFromBlob(error, fallback) {
  const data = error?.response?.data
  if (!(data instanceof Blob)) return data?.detail || error?.message || fallback
  try {
    const parsed = JSON.parse(await data.text())
    return parsed.detail || fallback
  } catch {
    return fallback
  }
}
