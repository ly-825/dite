import request from '../utils/request'

// 注册接口。
export function registerUser(data) {
  return request({
    url: '/api/auth/register',
    method: 'post',
    data
  })
}

// 登录接口。
export function loginUser(data) {
  return request({
    url: '/api/auth/login',
    method: 'post',
    data
  })
}

// 获取当前用户信息接口。
export function getCurrentUser() {
  return request({
    url: '/api/auth/me',
    method: 'get'
  })
}

