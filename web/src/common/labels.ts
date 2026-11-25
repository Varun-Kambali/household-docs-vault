// What a result row calls a document, which of them carry an ID number a row masks, and which are
// cards. Pinned to doctypes.py and the search vocabulary by a Python test.
export const TYPE_LABELS: Record<string, string> = {
  life_policy: 'Life policy',
  health_policy: 'Health policy',
  vehicle_policy: 'Vehicle policy',
  home_policy: 'Home policy',
  travel_policy: 'Travel policy',
  gadget_policy: 'Gadget policy',
  accident_policy: 'Accident policy',
  tax_invoice: 'Invoice',
  warranty_card: 'Warranty card',
  extended_warranty: 'Extended warranty',
  amc: 'Maintenance contract',
  appliance_service_record: 'Service record',
  aadhaar: 'Aadhaar',
  pan: 'PAN card',
  passport: 'Passport',
  voter_id: 'Voter ID',
  driving_licence: 'Driving licence',
  birth_certificate: 'Birth certificate',
  marriage_certificate: 'Marriage certificate',
  sale_deed: 'Sale deed',
  rent_agreement: 'Rent agreement',
  khata: 'Khata',
  property_tax_receipt: 'Property tax receipt',
  encumbrance_certificate: 'Encumbrance certificate',
  utility_bill: 'Utility bill',
  registration_certificate: 'RC',
  puc_certificate: 'PUC certificate',
  fastag: 'FASTag',
  vehicle_service_record: 'Vehicle service record',
  payslip: 'Payslip',
  offer_letter: 'Offer letter',
  appointment_letter: 'Appointment letter',
  appraisal_letter: 'Appraisal letter',
  relieving_letter: 'Relieving letter',
  experience_letter: 'Experience letter',
  certificate: 'Certificate',
  marksheet: 'Marksheet',
  degree: 'Degree',
  form_16: 'Form 16',
  itr_acknowledgement: 'ITR acknowledgement',
  tax_proof: 'Tax proof',
  card_front: 'Card',
  card_statement: 'Card statement',
  card_welcome_letter: 'Card welcome letter',
  prescription: 'Prescription',
  lab_report: 'Lab report',
  scan_photo: 'Scan',
  scan_report: 'Scan report',
  discharge_summary: 'Discharge summary',
  hospital_bill: 'Hospital bill',
  visit_recording: 'Visit recording',
  other: 'Unsorted document',
}

// ID numbers show as their last four digits until the owner asks (MASKED_FIELDS in vocab.py).
export const MASKED_TYPES = ['aadhaar', 'pan', 'passport', 'voter_id', 'driving_licence']

// A card's number and CVV never reach this app: they live in Secrets.kdbx.
export const CARD_TYPES = ['card_front', 'card_statement', 'card_welcome_letter']

export const CARD_NOTE =
  'The card number and CVV are kept in Secrets.kdbx and open with the master password.'

export function typeLabel(docType: string): string {
  return TYPE_LABELS[docType] ?? docType
}

export function isMasked(docType: string, field: string): boolean {
  return field === 'number' && MASKED_TYPES.includes(docType)
}

export function isCard(docType: string): boolean {
  return CARD_TYPES.includes(docType)
}

// The last four characters of an ID number, behind dots. A short value shows only dots.
export function lastFour(value: string): string {
  const compact = value.replace(/\s+/g, '')
  return compact.length > 4
    ? `\u2022\u2022\u2022\u2022 ${compact.slice(-4)}`
    : '\u2022\u2022\u2022\u2022'
}
