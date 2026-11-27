// A password box: masked, never remembered by the browser, with its label always visible.
import { useId } from 'react'

export function PasswordField({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (value: string) => void
}) {
  const id = useId()
  return (
    <div className="field-row">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        className="prompt"
        type="password"
        autoComplete="off"
        spellCheck={false}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  )
}
