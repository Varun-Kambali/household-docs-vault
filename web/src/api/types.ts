// The shapes the search and page routes answer with, as the API's own schema names them.
import type { components } from './schema.d.ts'

type Schemas = components['schemas']

export type SearchOut = Schemas['SearchOut']
export type RowOut = Schemas['RowOut']
export type AnswerOut = Schemas['AnswerOut']
export type NoAnswerOut = Schemas['NoAnswerOut']
export type LineRefOut = Schemas['LineRefOut']
export type PageLinesOut = Schemas['PageLinesOut']
export type DocumentOut = Schemas['DocumentOut']
export type PersonOut = Schemas['PersonOut']
export type QueryOut = Schemas['Query']
export type QueryIn = Schemas['QueryIn']
export type SentenceOut = Schemas['SentenceOut']
export type PartOut = Schemas['PartOut']
export type PartChange = Schemas['PartChange']
export type ListOut = Schemas['ListOut']
