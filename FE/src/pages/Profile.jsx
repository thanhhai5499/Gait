import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { User, Save, CheckCircle2, AlertCircle } from 'lucide-react'
import toast from 'react-hot-toast'
import useAuthStore from '../store/authStore'
import { updateMyProfile } from '../api/auth'

const SEX_OPTIONS = [
  { value: 'male',   label: 'Nam' },
  { value: 'female', label: 'Nữ' },
]

function validate(form) {
  const errors = {}
  const age = Number(form.age)
  const weight = Number(form.weight_kg)
  const height = Number(form.height_cm)

  if (!form.age && form.age !== 0)        errors.age       = 'Vui lòng nhập tuổi.'
  else if (age < 18)                       errors.age       = 'Tuổi tối thiểu là 18.'
  else if (age > 90)                       errors.age       = 'Tuổi tối đa là 90 (theo dataset tham chiếu).'

  if (!form.sex)                           errors.sex       = 'Vui lòng chọn giới tính.'

  if (!form.weight_kg && form.weight_kg !== 0) errors.weight_kg = 'Vui lòng nhập cân nặng.'
  else if (weight < 20)                    errors.weight_kg = 'Cân nặng tối thiểu là 20 kg.'
  else if (weight > 100)                   errors.weight_kg = 'Cân nặng tối đa là 100 kg.'

  if (!form.height_cm && form.height_cm !== 0) errors.height_cm = 'Vui lòng nhập chiều cao.'
  else if (height < 50)                    errors.height_cm = 'Chiều cao tối thiểu là 50 cm.'
  else if (height > 200)                   errors.height_cm = 'Chiều cao tối đa là 200 cm.'

  return errors
}

function Field({ label, required, children, error, hint }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-sm font-medium text-gray-700">
        {label}
        {required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      {children}
      {error
        ? <p className="text-xs text-red-500 flex items-center gap-1"><AlertCircle size={11} />{error}</p>
        : hint
        ? <p className="text-xs text-gray-400">{hint}</p>
        : null
      }
    </div>
  )
}

export default function Profile() {
  const { user, setUser } = useAuthStore()

  const [form, setForm] = useState({
    full_name:  user?.full_name  ?? '',
    age:        user?.age        ?? '',
    sex:        user?.sex        ?? '',
    weight_kg:  user?.weight_kg  ?? '',
    height_cm:  user?.height_cm  ?? '',
  })

  const [errors, setErrors]   = useState({})
  const [touched, setTouched] = useState({})

  const profileComplete = user?.profile_complete ?? false

  const mutation = useMutation({
    mutationFn: () => updateMyProfile({
      full_name: form.full_name || undefined,
      age:       form.age       ? Number(form.age)       : undefined,
      sex:       form.sex       || undefined,
      weight_kg: form.weight_kg ? Number(form.weight_kg) : undefined,
      height_cm: form.height_cm ? Number(form.height_cm) : undefined,
    }),
    onSuccess: (res) => {
      setUser(res.data)
      setErrors({})
      toast.success('Đã cập nhật thông tin cá nhân')
    },
    onError: (e) => {
      toast.error(e.response?.data?.detail || 'Không thể cập nhật thông tin')
    },
  })

  const handleChange = (e) => {
    const { name, value } = e.target
    const next = { ...form, [name]: value }
    setForm(next)
    if (touched[name]) {
      const errs = validate(next)
      setErrors((prev) => ({ ...prev, [name]: errs[name] }))
    }
  }

  const handleBlur = (e) => {
    const { name } = e.target
    setTouched((prev) => ({ ...prev, [name]: true }))
    const errs = validate(form)
    setErrors((prev) => ({ ...prev, [name]: errs[name] }))
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    const allTouched = { age: true, sex: true, weight_kg: true, height_cm: true }
    setTouched(allTouched)
    const errs = validate(form)
    setErrors(errs)
    if (Object.keys(errs).length > 0) return
    mutation.mutate()
  }

  const inputClass = (name) =>
    `border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 transition-colors ${
      errors[name] && touched[name]
        ? 'border-red-400 focus:ring-red-300 bg-red-50'
        : 'border-gray-300 focus:ring-blue-500'
    }`

  return (
    <div className="px-6 pt-20 pb-10 max-w-lg mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center">
          <User size={20} className="text-blue-600" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-gray-800">Thông tin cá nhân</h1>
          <p className="text-sm text-gray-500">Dùng cho phân tích dáng đi chuẩn hóa theo dataset</p>
        </div>
      </div>

      {/* Profile completeness banner */}
      {profileComplete ? (
        <div className="flex items-center gap-2 bg-green-50 border border-green-200 rounded-xl px-4 py-3 text-sm text-green-700">
          <CheckCircle2 size={16} />
          Thông tin đầy đủ — bạn có thể kết nối đo lường.
        </div>
      ) : (
        <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-700">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <span>
            Bạn chưa điền đủ thông tin cá nhân (tuổi, giới tính, cân nặng, chiều cao).
            Vui lòng hoàn tất để sử dụng.
          </span>
        </div>
      )}

      {/* Form */}
      <form onSubmit={handleSubmit} className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 space-y-5" noValidate>

        <Field label="Họ và tên">
          <input
            name="full_name"
            value={form.full_name}
            onChange={handleChange}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </Field>

        <div className="grid grid-cols-2 gap-4">
          <Field label="Tuổi" required hint="18 – 90 tuổi" error={touched.age ? errors.age : undefined}>
            <input
              type="number"
              name="age"
              value={form.age}
              onChange={handleChange}
              onBlur={handleBlur}
              min={18}
              max={90}
              placeholder="VD: 28"
              className={inputClass('age')}
            />
          </Field>

          <Field label="Giới tính" required error={touched.sex ? errors.sex : undefined}>
            <select
              name="sex"
              value={form.sex}
              onChange={handleChange}
              onBlur={handleBlur}
              className={`${inputClass('sex')} bg-white`}
            >
              <option value="">-- Chọn --</option>
              {SEX_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </Field>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <Field label="Cân nặng (kg)" required hint="20 – 100 kg" error={touched.weight_kg ? errors.weight_kg : undefined}>
            <input
              type="number"
              name="weight_kg"
              value={form.weight_kg}
              onChange={handleChange}
              onBlur={handleBlur}
              min={20}
              max={100}
              step={0.1}
              placeholder="VD: 65"
              className={inputClass('weight_kg')}
            />
          </Field>

          <Field label="Chiều cao (cm)" required hint="50 – 200 cm" error={touched.height_cm ? errors.height_cm : undefined}>
            <input
              type="number"
              name="height_cm"
              value={form.height_cm}
              onChange={handleChange}
              onBlur={handleBlur}
              min={50}
              max={200}
              step={0.1}
              placeholder="VD: 170"
              className={inputClass('height_cm')}
            />
          </Field>
        </div>

        <button
          type="submit"
          disabled={mutation.isPending}
          className="flex items-center gap-2 px-5 py-2 rounded-lg font-semibold text-sm bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          <Save size={15} />
          {mutation.isPending ? 'Đang lưu...' : 'Lưu thay đổi'}
        </button>
      </form>

      {/* Read-only account info */}
      <div className="bg-gray-50 rounded-2xl border border-gray-200 px-5 py-4 space-y-2">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Thông tin tài khoản</p>
        {[
          { label: 'Tên đăng nhập', value: user?.username },
          { label: 'Email',         value: user?.email },
          { label: 'Vai trò',       value: user?.role === 'admin' ? 'Quản trị viên' : 'Người dùng' },
        ].map(({ label, value }) => (
          <div key={label} className="flex justify-between text-sm">
            <span className="text-gray-500">{label}</span>
            <span className="font-medium text-gray-800">{value ?? '—'}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
