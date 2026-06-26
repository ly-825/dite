import request from '../utils/request'

export function getMealRecords(params = {}) {
  return request({
    url: '/api/meals/records',
    method: 'get',
    params
  })
}

export function getMealReview(params = {}) {
  return request({
    url: '/api/meals/review',
    method: 'get',
    params
  })
}

export function deleteMealRecord(recordId, params = {}) {
  return request({
    url: `/api/meals/records/${recordId}`,
    method: 'delete',
    params
  })
}

export function updateMealRecordFeedback(recordId, data, params = {}) {
  return request({
    url: `/api/meals/records/${recordId}/feedback`,
    method: 'patch',
    data,
    params
  })
}
