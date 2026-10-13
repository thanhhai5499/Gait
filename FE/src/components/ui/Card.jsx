export default function Card({ title, children }) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
      <h3 className="font-semibold text-gray-700 mb-4 text-sm uppercase tracking-wide">{title}</h3>
      {children}
    </div>
  )
}
