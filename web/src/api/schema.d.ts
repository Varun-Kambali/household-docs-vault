// Generated from the API by web/scripts/generate-types.ts. Do not edit by hand:
// change the API, then run `npm run types` in web/.
export interface paths {
  '/healthz': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Healthz */
    get: operations['healthz_healthz_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/activity': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Activity */
    get: operations['activity_v1_activity_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/cards': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Upload Card */
    post: operations['upload_card_v1_cards_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/documents/{doc_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Document */
    get: operations['document_v1_documents__doc_id__get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/documents/{doc_id}/file': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Document File */
    get: operations['document_file_v1_documents__doc_id__file_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/documents/{doc_id}/pages/{page}.png': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Document Page */
    get: operations['document_page_v1_documents__doc_id__pages__page__png_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/documents/{doc_id}/pages/{page}/lines': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Document Lines */
    get: operations['document_lines_v1_documents__doc_id__pages__page__lines_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/documents/{doc_id}/reveal': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Reveal */
    post: operations['reveal_v1_documents__doc_id__reveal_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/documents/{doc_id}/undo': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Undo Document */
    post: operations['undo_document_v1_documents__doc_id__undo_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/emergency-sheet': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Emergency Sheet */
    get: operations['emergency_sheet_v1_emergency_sheet_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/inbox/progress': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Progress */
    get: operations['progress_v1_inbox_progress_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/items/{item_id}/file': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Item File */
    get: operations['item_file_v1_items__item_id__file_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/items/{item_id}/pages/{page}.png': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Item Page */
    get: operations['item_page_v1_items__item_id__pages__page__png_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/items/{item_id}/pages/{page}/lines': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Item Lines */
    get: operations['item_lines_v1_items__item_id__pages__page__lines_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/items/{item_id}/retry': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Retry */
    post: operations['retry_v1_items__item_id__retry_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/needs-a-look': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Needs A Look */
    get: operations['needs_a_look_v1_needs_a_look_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/needs-a-look/answer-many': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Answer Many */
    post: operations['answer_many_v1_needs_a_look_answer_many_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/needs-a-look/{item_id}/answer': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Answer */
    post: operations['answer_v1_needs_a_look__item_id__answer_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/needs-a-look/{item_id}/undo': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Undo Item */
    post: operations['undo_item_v1_needs_a_look__item_id__undo_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/needs-a-look/{item_id}/unlock': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Unlock */
    post: operations['unlock_v1_needs_a_look__item_id__unlock_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/people': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** People */
    get: operations['people_v1_people_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/search': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Search */
    post: operations['search_v1_search_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/search/list': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Search List */
    post: operations['search_list_v1_search_list_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/secrets/create': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Secrets Create */
    post: operations['secrets_create_v1_secrets_create_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/v1/secrets/unlock': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Secrets Unlock */
    post: operations['secrets_unlock_v1_secrets_unlock_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
}
export type webhooks = Record<string, never>
export interface components {
  schemas: {
    /** ActivityOut */
    ActivityOut: {
      /** Actions */
      actions: string[]
      /** Detail */
      detail: string
      /** File */
      file: string | null
      /** Id */
      id: number
      /** Item Id */
      item_id: number | null
      /** Outcome */
      outcome: string
      /** Step */
      step: string
      /**
       * Time
       * Format: date-time
       */
      time: string
    }
    /** AnswerIn */
    AnswerIn: {
      /**
       * Confirm
       * @default false
       */
      confirm: boolean
      /** Field */
      field?: string | null
      /**
       * Kind
       * @enum {string}
       */
      kind: 'person' | 'type' | 'field' | 'copy' | 'unlock' | 'retry' | 'discard'
      /**
       * Value
       * @default
       */
      value: string
    }
    /** AnswerManyIn */
    AnswerManyIn: {
      /** Item Ids */
      item_ids: number[]
      /** Value */
      value: string
    }
    /** AnswerOut */
    AnswerOut: {
      /** Document Id */
      document_id: string
      /** Field */
      field: string
      /** Lines */
      lines: components['schemas']['LineRefOut'][]
      /** Masked */
      masked: boolean
      /** Page */
      page: number
      /** Text */
      text: string
      value: components['schemas']['JsonValue']
    }
    /**
     * Area
     * @description A folder group in the vault. The values are stored in the database.
     * @enum {string}
     */
    Area:
      | 'insurance'
      | 'purchases'
      | 'identity'
      | 'vehicle'
      | 'work'
      | 'education'
      | 'tax'
      | 'cards'
      | 'medical'
      | 'property'
      | 'rent'
      | 'utilities'
    /** CardOut */
    CardOut: {
      /** Document Id */
      document_id?: string | null
      /** Item Id */
      item_id?: number | null
      /** Status */
      status: string
    }
    /** ChoiceOut */
    ChoiceOut: {
      /** Label */
      label: string
      value: components['schemas']['JsonValue']
    }
    /**
     * DateRange
     * @description Both ends inclusive; a missing end is open.
     */
    DateRange: {
      /** End */
      end?: string | null
      /** Start */
      start?: string | null
    }
    /**
     * DocType
     * @enum {string}
     */
    DocType:
      | 'life_policy'
      | 'health_policy'
      | 'vehicle_policy'
      | 'home_policy'
      | 'travel_policy'
      | 'gadget_policy'
      | 'accident_policy'
      | 'tax_invoice'
      | 'warranty_card'
      | 'extended_warranty'
      | 'amc'
      | 'appliance_service_record'
      | 'aadhaar'
      | 'pan'
      | 'passport'
      | 'voter_id'
      | 'driving_licence'
      | 'birth_certificate'
      | 'marriage_certificate'
      | 'sale_deed'
      | 'rent_agreement'
      | 'khata'
      | 'property_tax_receipt'
      | 'encumbrance_certificate'
      | 'utility_bill'
      | 'registration_certificate'
      | 'puc_certificate'
      | 'fastag'
      | 'vehicle_service_record'
      | 'payslip'
      | 'offer_letter'
      | 'appointment_letter'
      | 'appraisal_letter'
      | 'relieving_letter'
      | 'experience_letter'
      | 'certificate'
      | 'marksheet'
      | 'degree'
      | 'form_16'
      | 'itr_acknowledgement'
      | 'tax_proof'
      | 'card_front'
      | 'card_statement'
      | 'card_welcome_letter'
      | 'prescription'
      | 'lab_report'
      | 'scan_photo'
      | 'scan_report'
      | 'discharge_summary'
      | 'hospital_bill'
      | 'visit_recording'
      | 'other'
    /** DocumentOut */
    DocumentOut: {
      /** Area */
      area: string
      /**
       * Created At
       * Format: date-time
       */
      created_at: string
      /** Date Source */
      date_source: string
      /** Description */
      description: string
      /**
       * Doc Date
       * Format: date
       */
      doc_date: string
      /** Doc Type */
      doc_type: string
      /** Drive Path */
      drive_path: string
      /** Field Kinds */
      field_kinds: {
        [key: string]: string
      }
      /** Fields */
      fields: {
        [key: string]: unknown
      }
      /** Id */
      id: string
      /** Issues */
      issues: {
        [key: string]: unknown
      }
      /** Item Id */
      item_id: number
      /** Owner */
      owner: string
      /** Page Count */
      page_count: number
      /** People */
      people: string[]
      /** Rel Path */
      rel_path: string
    }
    /** HTTPValidationError */
    HTTPValidationError: {
      /** Detail */
      detail?: components['schemas']['ValidationError'][]
    }
    /** Health */
    Health: {
      /** Reader */
      reader: string
      /** Status */
      status: string
      /** Version */
      version: string
    }
    /** ItemOut */
    ItemOut: {
      /** Id */
      id: number
      /** State */
      state: string
    }
    JsonValue: unknown
    /** LineOut */
    LineOut: {
      /** Bbox */
      bbox: [number, number, number, number]
      /** Idx */
      idx: number
      /** Text */
      text: string
    }
    /** LineRefOut */
    LineRefOut: {
      /** Bbox */
      bbox: [number, number, number, number]
      /** Idx */
      idx: number
      /** Page */
      page: number
    }
    /** ListIn */
    ListIn: {
      change?: components['schemas']['PartChange'] | null
      query: components['schemas']['QueryIn']
    }
    /** MasterPasswordIn */
    MasterPasswordIn: {
      /** Master Password */
      master_password: string
    }
    /** NeedsALookOut */
    NeedsALookOut: {
      /** File */
      file: string | null
      /** Id */
      id: number
      /** Name */
      name: string
      question: components['schemas']['QuestionOut']
      /** Reasons */
      reasons: string[]
      /**
       * Since
       * Format: date-time
       */
      since: string
    }
    /** NoAnswerOut */
    NoAnswerOut: {
      /** Closest */
      closest: string[]
      /**
       * Reason
       * @enum {string}
       */
      reason: 'no_documents' | 'unknown_person' | 'weak_match' | 'no_field' | 'not_on_page'
    }
    /** OptionOut */
    OptionOut: {
      /** Label */
      label: string
      /** Value */
      value: string
    }
    /** PageLinesOut */
    PageLinesOut: {
      /** Lines */
      lines: components['schemas']['LineOut'][]
      /** Page */
      page: number
    }
    /** PartChange */
    PartChange: {
      /** Slot */
      slot: string
      value?: components['schemas']['JsonValue']
    }
    /** PartOut */
    PartOut: {
      /** Options */
      options: components['schemas']['ChoiceOut'][]
      /** Slot */
      slot: string
      /** Text */
      text: string
      value: components['schemas']['JsonValue']
    }
    /** PersonOut */
    PersonOut: {
      /** Id */
      id: string
      /** Name */
      name: string
    }
    /** ProgressOut */
    ProgressOut: {
      /** Asked In Batch */
      asked_in_batch: number
      /** Batch Started At */
      batch_started_at: string | null
      /** Current */
      current: string | null
      /** Done In Batch */
      done_in_batch: number
      /** Step */
      step: string | null
      /** Total In Batch */
      total_in_batch: number
      /** Waiting */
      waiting: number
    }
    /**
     * Query
     * @description A reading with people and dates worked out by code. Also the list route's body.
     *
     *     `backstop_conflicts` is for the eval only: it is left out of every serialised form, so the
     *     API and the app never show it.
     */
    Query: {
      /**
       * Areas
       * @default []
       */
      areas: components['schemas']['Area'][]
      /** Field */
      field?: string | null
      /**
       * Intent
       * @enum {string}
       */
      intent: 'lookup' | 'list' | 'find'
      /**
       * People
       * @default []
       */
      people: string[]
      /** Place */
      place?: string | null
      range?: components['schemas']['DateRange'] | null
      /** Role */
      role?: ('expiry' | 'renewal' | 'due' | 'purchase' | 'issue' | 'document') | null
      /**
       * Types
       * @default []
       */
      types: components['schemas']['DocType'][]
      /**
       * Unread
       * @default []
       */
      unread: string[]
      /**
       * Words
       * @default
       */
      words: string
    }
    /**
     * QueryIn
     * @description A query as the screen sends it back: the same shape the search returned.
     */
    QueryIn: {
      /**
       * Areas
       * @default []
       */
      areas: components['schemas']['Area'][]
      /** Field */
      field?: string | null
      /**
       * Intent
       * @enum {string}
       */
      intent: 'lookup' | 'list' | 'find'
      /**
       * People
       * @default []
       */
      people: string[]
      /** Place */
      place?: string | null
      range?: components['schemas']['DateRange'] | null
      /** Role */
      role?: ('expiry' | 'renewal' | 'due' | 'purchase' | 'issue' | 'document') | null
      /**
       * Types
       * @default []
       */
      types: components['schemas']['DocType'][]
      /**
       * Unread
       * @default []
       */
      unread: string[]
      /**
       * Words
       * @default
       */
      words: string
    }
    /** QuestionOut */
    QuestionOut: {
      /** Answer Kind */
      answer_kind: string
      /** Field */
      field?: string | null
      /** Options */
      options: components['schemas']['OptionOut'][]
      /** Reason */
      reason: string
      /** Text */
      text: string
    }
    /** RowOut */
    RowOut: {
      /** Area */
      area: string
      /** Date */
      date: string | null
      /**
       * Doc Date
       * Format: date
       */
      doc_date: string
      /** Doc Type */
      doc_type: string
      /** Document Id */
      document_id: string
      /** Drive Path */
      drive_path: string
      /** Key Fields */
      key_fields: {
        [key: string]: components['schemas']['JsonValue']
      }
      /** Lines */
      lines: components['schemas']['LineRefOut'][]
      /** Owner */
      owner: string
      /** People */
      people: string[]
      /** Rel Path */
      rel_path: string
      /** Score */
      score: number
    }
    /** SearchIn */
    SearchIn: {
      /**
       * Full
       * @default false
       */
      full: boolean
      /** Prompt */
      prompt: string
    }
    /** SearchOut */
    SearchOut: {
      answer?: components['schemas']['AnswerOut'] | null
      no_answer?: components['schemas']['NoAnswerOut'] | null
      query?: components['schemas']['Query'] | null
      /**
       * Reading
       * @enum {string}
       */
      reading: 'on' | 'off'
      /** Rows */
      rows: components['schemas']['RowOut'][]
      sentence?: components['schemas']['SentenceOut'] | null
      /**
       * Vectors
       * @enum {string}
       */
      vectors: 'on' | 'off' | 'stale'
    }
    /** SentenceOut */
    SentenceOut: {
      /** Parts */
      parts: components['schemas']['PartOut'][]
      /** Text */
      text: string
    }
    /** UnlockIn */
    UnlockIn: {
      /** Master Password */
      master_password?: string | null
      /** Password */
      password: string
      /**
       * Save
       * @default false
       */
      save: boolean
    }
    /** ValidationError */
    ValidationError: {
      /** Context */
      ctx?: Record<string, never>
      /** Input */
      input?: unknown
      /** Location */
      loc: (string | number)[]
      /** Message */
      msg: string
      /** Error Type */
      type: string
    }
  }
  responses: never
  parameters: never
  requestBodies: never
  headers: never
  pathItems: never
}
export type $defs = Record<string, never>
export interface operations {
  healthz_healthz_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['Health']
        }
      }
    }
  }
  activity_v1_activity_get: {
    parameters: {
      query?: {
        limit?: number
        before?: number | null
      }
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ActivityOut'][]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  upload_card_v1_cards_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['CardOut']
        }
      }
    }
  }
  document_v1_documents__doc_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        doc_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['DocumentOut']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  document_file_v1_documents__doc_id__file_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        doc_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  document_page_v1_documents__doc_id__pages__page__png_get: {
    parameters: {
      query?: {
        width?: number
      }
      header?: never
      path: {
        doc_id: string
        page: number
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  document_lines_v1_documents__doc_id__pages__page__lines_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        doc_id: string
        page: number
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['PageLinesOut']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  reveal_v1_documents__doc_id__reveal_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        doc_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  undo_document_v1_documents__doc_id__undo_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        doc_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ItemOut']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  emergency_sheet_v1_emergency_sheet_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': unknown
        }
      }
    }
  }
  progress_v1_inbox_progress_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ProgressOut']
        }
      }
    }
  }
  item_file_v1_items__item_id__file_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        item_id: number
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  item_page_v1_items__item_id__pages__page__png_get: {
    parameters: {
      query?: {
        width?: number
      }
      header?: never
      path: {
        item_id: number
        page: number
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  item_lines_v1_items__item_id__pages__page__lines_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        item_id: number
        page: number
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['PageLinesOut']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  retry_v1_items__item_id__retry_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        item_id: number
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ItemOut']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  needs_a_look_v1_needs_a_look_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['NeedsALookOut'][]
        }
      }
    }
  }
  answer_many_v1_needs_a_look_answer_many_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['AnswerManyIn']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ItemOut'][]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  answer_v1_needs_a_look__item_id__answer_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        item_id: number
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['AnswerIn']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ItemOut']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  undo_item_v1_needs_a_look__item_id__undo_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        item_id: number
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ItemOut']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  unlock_v1_needs_a_look__item_id__unlock_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        item_id: number
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['UnlockIn']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ItemOut']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  people_v1_people_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['PersonOut'][]
        }
      }
    }
  }
  search_v1_search_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['SearchIn']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['SearchOut']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  search_list_v1_search_list_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['ListIn']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  secrets_create_v1_secrets_create_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['MasterPasswordIn']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': {
            [key: string]: string
          }
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  secrets_unlock_v1_secrets_unlock_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['MasterPasswordIn']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': {
            [key: string]: string
          }
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
}
