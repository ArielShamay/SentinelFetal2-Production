// src/components/god-mode/DetectionDetail.tsx
// Inline expandable panel showing which clinical features were overridden
// and their injected values. Shown inside GodModePanel's active event rows.

import React from 'react'

// Feature labels mapping CLINICAL_FEATURE_NAMES → human-readable strings
const FEATURE_LABELS: Record<string, string> = {
  baseline_bpm:               'Baseline',
  is_tachycardia:             'Tachycardia',
  is_bradycardia:             'Bradycardia',
  variability_amplitude_bpm:  'Variability Amplitude',
  variability_category:       'Variability Category',
  n_late_decelerations:       'Late Decels',
  n_variable_decelerations:   'Variable Decels',
  n_prolonged_decelerations:  'Prolonged Decels',
  max_deceleration_depth_bpm: 'Max Decel Depth',
  sinusoidal_detected:        'Sinusoidal',
  tachysystole_detected:      'Tachysystole',
}

const FEATURE_UNITS: Record<string, string> = {
  baseline_bpm:               'bpm',
  variability_amplitude_bpm:  'bpm',
  max_deceleration_depth_bpm: 'bpm',
}

interface Props {
  detectedDetails: Record<string, number>
}

export const DetectionDetail: React.FC<Props> = ({ detectedDetails }) => {
  const entries = Object.entries(detectedDetails)
  if (entries.length === 0) {
    return <p className="text-xs text-gray-400 mt-2">אין פרטי override</p>
  }

  return (
    <div className="mt-2">
      <p className="text-xs font-medium text-gray-500 mb-1">Feature overrides:</p>
      <table className="w-full text-xs font-mono">
        <tbody>
          {entries.map(([key, value]) => (
            <tr key={key} className="border-t border-gray-100">
              <td className="py-0.5 pr-4 text-gray-500">
                {FEATURE_LABELS[key] ?? key}
              </td>
              <td className="py-0.5 text-gray-900 font-semibold">
                {typeof value === 'number' ? value.toFixed(1) : String(value)}
                {FEATURE_UNITS[key] ? ` ${FEATURE_UNITS[key]}` : ''}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
