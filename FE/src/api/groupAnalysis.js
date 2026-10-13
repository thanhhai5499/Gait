import api from './axios'

export const getGroupAnalysis = ({ sex, ageMin, ageMax }) =>
  api.get('/admin/group-analysis', { params: { sex: sex || undefined, age_min: ageMin, age_max: ageMax } })
