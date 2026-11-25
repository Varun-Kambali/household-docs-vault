// The household's names, by id, for the rows that carry ids. Read once; if it cannot be read,
// the rows show no names rather than ids.
import { useEffect, useState } from 'react'

import { api, isAbort } from '../api/client.ts'
import type { PersonOut } from '../api/types.ts'

export function usePeople(): ReadonlyMap<string, string> {
  const [names, setNames] = useState<ReadonlyMap<string, string>>(new Map())
  useEffect(() => {
    const controller = new AbortController()
    api<PersonOut[]>('/v1/people', { signal: controller.signal })
      .then((people) => {
        if (Array.isArray(people)) {
          setNames(new Map(people.map((person) => [person.id, person.name])))
        }
      })
      .catch((error: unknown) => {
        if (!isAbort(error)) setNames(new Map())
      })
    return () => controller.abort()
  }, [])
  return names
}
