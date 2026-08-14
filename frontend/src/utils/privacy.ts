export const maskStudentId = (value: string) => {
  if (value.length <= 4) return '*'.repeat(value.length)
  return `${value.slice(0, 2)}${'*'.repeat(Math.max(4, value.length - 4))}${value.slice(-2)}`
}

export const maskEmail = (value: string) => {
  const [localPart, domain] = value.split('@')
  if (!domain) return '***'
  const visible = localPart.length > 2 ? `${localPart.slice(0, 2)}***` : '***'
  return `${visible}@${domain}`
}
