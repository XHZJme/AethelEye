/**
 * 筱和灵眸(AethelEye) - 用户状态管理 (Pinia)
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi, getToken, setToken, removeToken, UserInfo } from '@/api'

export const useUserStore = defineStore('user', () => {
  // 状态
  const token = ref<string | null>(getToken())
  const userInfo = ref<UserInfo | null>(null)
  const loading = ref(false)

  // 计算属性
  const isLoggedIn = computed(() => !!token.value)
  const username = computed(() => userInfo.value?.username || '')
  const role = computed(() => userInfo.value?.role || '')
  const isAdmin = computed(() => role.value === 'admin')
  const isOperator = computed(() => role.value === 'operator' || isAdmin.value)
  const isViewer = computed(() => role.value === 'viewer')

  // 方法
  async function login(username: string, password: string, rememberMe: boolean = false) {
    loading.value = true
    try {
      const response = await authApi.login({
        username,
        password,
        remember_me: rememberMe,
      })
      token.value = response.token
      setToken(response.token)
      userInfo.value = {
        id: response.user_id,
        username: response.username,
        role: response.role,
        is_active: true,
        last_login_at: null,
      }
      return true
    } catch (error) {
      return false
    } finally {
      loading.value = false
    }
  }

  async function initAdmin(username: string, password: string) {
    loading.value = true
    try {
      const response = await authApi.initAdmin({
        username,
        password,
      })
      token.value = response.token
      setToken(response.token)
      userInfo.value = {
        id: response.user_id,
        username: response.username,
        role: response.role,
        is_active: true,
        last_login_at: null,
      }
      return true
    } catch (error) {
      return false
    } finally {
      loading.value = false
    }
  }

  async function logout() {
    try {
      await authApi.logout()
    } catch (error) {
      // 忽略登出错误
    }
    token.value = null
    userInfo.value = null
    removeToken()
  }

  async function fetchUserInfo() {
    if (!token.value) return
    loading.value = true
    try {
      const info = await authApi.getCurrentUser()
      userInfo.value = info
    } catch (error) {
      // Token无效，清除登录状态
      token.value = null
      userInfo.value = null
      removeToken()
    } finally {
      loading.value = false
    }
  }

  async function checkInitStatus() {
    try {
      const status = await authApi.getInitStatus()
      return status
    } catch (error) {
      // 后端不可达时不能误判为“首次初始化”，否则会把登录页错误跳转到初始化页
      return { need_init: false, message: '无法连接服务器，请确认后端服务已启动' }
    }
  }

  return {
    // 状态
    token,
    userInfo,
    loading,
    // 计算属性
    isLoggedIn,
    username,
    role,
    isAdmin,
    isOperator,
    isViewer,
    // 方法
    login,
    initAdmin,
    logout,
    fetchUserInfo,
    checkInitStatus,
  }
})
