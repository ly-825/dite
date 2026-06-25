import request from '../utils/request'

export function getProfileBundle() {
  return request({
    url: '/api/profile',
    method: 'get'
  })
}

export function updateProfile(data) {
  return request({
    url: '/api/profile',
    method: 'put',
    data
  })
}

export function confirmMemory(memoryId) {
  return request({
    url: `/api/profile/memories/${memoryId}/confirm`,
    method: 'post'
  })
}

export function rejectMemory(memoryId) {
  return request({
    url: `/api/profile/memories/${memoryId}/reject`,
    method: 'post'
  })
}

export function deleteMemory(memoryId) {
  return request({
    url: `/api/profile/memories/${memoryId}`,
    method: 'delete'
  })
}

export function createRecipeFeedback(data) {
  return request({
    url: '/api/profile/recipe-feedbacks',
    method: 'post',
    data
  })
}
