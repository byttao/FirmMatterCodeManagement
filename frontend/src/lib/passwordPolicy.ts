export const LOGIN_PASSWORD_HINT = '至少8位，且同时包含英文字母和数字'
export const LOGIN_PASSWORD_PATTERN = '(?=.*[A-Za-z])(?=.*[0-9]).{8,72}'

export function loginPasswordError(password: string): string | null {
  if (password.length < 8 || password.length > 72 || new TextEncoder().encode(password).length > 72
      || !/[A-Za-z]/.test(password) || !/[0-9]/.test(password)) {
    return '登录密码需为8至72位，且同时包含英文字母和数字；UTF-8编码不能超过72字节'
  }
  return null
}
