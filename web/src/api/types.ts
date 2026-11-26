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

// What POST /v1/search/list answers. The route has no response model of its own, so the shape is
// written here: the rows, the sentence over them, and the query that made both.
export type ListOut = {
  rows: RowOut[]
  sentence: SentenceOut
  query: QueryOut
}
