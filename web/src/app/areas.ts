// The vault's twelve areas, in the order of `Area` in doctypes.py (a Python test pins the order),
// with the labels the search vocabulary calls them, in sentence case.
export const AREAS = [
  { id: 'insurance', label: 'Insurance' },
  { id: 'purchases', label: 'Purchases' },
  { id: 'identity', label: 'Identity' },
  { id: 'vehicle', label: 'Vehicle' },
  { id: 'work', label: 'Work' },
  { id: 'education', label: 'Education' },
  { id: 'tax', label: 'Tax' },
  { id: 'cards', label: 'Cards' },
  { id: 'medical', label: 'Medical' },
  { id: 'property', label: 'Property' },
  { id: 'rent', label: 'Rent' },
  { id: 'utilities', label: 'Utilities' },
] as const

export type AreaId = (typeof AREAS)[number]['id']

export function isAreaId(value: string): value is AreaId {
  return AREAS.some((area) => area.id === value)
}
