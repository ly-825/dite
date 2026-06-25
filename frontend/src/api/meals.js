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
