// Native browser validation otherwise follows the browser's language, which may be English.
export function installChineseValidation() {
  const editable = (target: EventTarget | null): target is HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement => target instanceof HTMLInputElement || target instanceof HTMLSelectElement || target instanceof HTMLTextAreaElement
  document.addEventListener('invalid', event => {
    if (!editable(event.target)) return
    const field = event.target
    field.setCustomValidity('')
    const value = field.validity
    const message = value.valueMissing ? '请填写或选择此必填项' : value.typeMismatch ? '输入格式不正确，请检查邮箱或网址格式' : value.rangeUnderflow || value.rangeOverflow ? '输入数值超出允许范围，请检查上下限' : value.tooShort || value.tooLong ? '输入长度不符合要求，请检查字符数量' : value.stepMismatch || value.badInput ? '请输入符合要求的有效数值' : value.patternMismatch ? '输入格式不符合要求，请按页面说明填写' : '输入内容不符合要求，请检查后重试'
    field.setCustomValidity(message)
  }, true)
  const clear = (event: Event) => { if (editable(event.target)) event.target.setCustomValidity('') }
  document.addEventListener('input', clear, true)
  document.addEventListener('change', clear, true)
}
