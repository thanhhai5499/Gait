import { useState } from 'react'
import toast from 'react-hot-toast'
import { exportSessionCsv } from '../api/sessions'
import { filenameFromResponse, saveBlob, errorMessageFromBlob } from '../utils/downloadFile'

/**
 * Xuất dữ liệu thô của một phiên đo ra tệp CSV.
 * `exportCsv` nhận object phiên đo (hoặc id); `exportingId` để vô hiệu hóa nút đang chạy.
 */
export function useExportCsv() {
  const [exportingId, setExportingId] = useState(null)

  const exportCsv = async (session) => {
    const id = typeof session === 'object' ? session?.id : session
    if (!id) return
    const code = typeof session === 'object' ? session?.session_code : null

    setExportingId(id)
    try {
      const res = await exportSessionCsv(id)
      const filename = filenameFromResponse(res, `session_${code ?? id}.csv`)
      saveBlob(res.data, filename)
      toast.success(`Đã xuất ${filename}`)
    } catch (e) {
      toast.error(await errorMessageFromBlob(e, 'Không thể xuất tệp CSV'))
    } finally {
      setExportingId(null)
    }
  }

  return { exportCsv, exportingId }
}
