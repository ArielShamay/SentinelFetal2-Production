// Shared wall-clock formatting for the clinical UI.
// All timestamps are Unix seconds (UTC); display is Israel local time.

const timeWithSecondsFormatter = new Intl.DateTimeFormat('he-IL', {
  timeZone: 'Asia/Jerusalem',
  hour12: false,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

const timeWithoutSecondsFormatter = new Intl.DateTimeFormat('he-IL', {
  timeZone: 'Asia/Jerusalem',
  hour12: false,
  hour: '2-digit',
  minute: '2-digit',
})

const dateTimeFormatter = new Intl.DateTimeFormat('he-IL', {
  timeZone: 'Asia/Jerusalem',
  hour12: false,
  year: '2-digit',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

export function formatIsraelTime(unixSec: number, withSeconds = true): string {
  if (!Number.isFinite(unixSec) || unixSec <= 0) return '--:--'
  const date = new Date(unixSec * 1000)
  return withSeconds
    ? timeWithSecondsFormatter.format(date)
    : timeWithoutSecondsFormatter.format(date)
}

export function formatIsraelTimeWithDate(unixSec: number): string {
  if (!Number.isFinite(unixSec) || unixSec <= 0) return '--'
  return dateTimeFormatter.format(new Date(unixSec * 1000))
}
