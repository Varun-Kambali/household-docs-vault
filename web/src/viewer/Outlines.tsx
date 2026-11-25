// The cited lines, drawn on the page image. A box is the line's position on the page, as a share
// of its width and height. Each one has a 2 px border with an offset as well as a tint, so it is
// not told apart by colour alone. A box is a button named by its line: in a result it opens the
// viewer at that line, and in the viewer it moves the mark to that line.
export type Outline = {
  idx: number
  bbox: readonly [number, number, number, number]
  text?: string | undefined
}

function name(outline: Outline): string {
  const text = outline.text?.trim() ?? ''
  const short = text.length > 40 ? `${text.slice(0, 40)}...` : text
  return short === '' ? `Line ${outline.idx + 1}` : `Line ${outline.idx + 1}: ${short}`
}

function place(bbox: Outline['bbox']) {
  const [x0, y0, x1, y1] = bbox
  return {
    left: `${x0 * 100}%`,
    top: `${y0 * 100}%`,
    width: `${(x1 - x0) * 100}%`,
    height: `${(y1 - y0) * 100}%`,
  }
}

export function Outlines({
  outlines,
  onOpen,
}: {
  outlines: Outline[]
  onOpen: (idx: number) => void
}) {
  return (
    <>
      {outlines.map((outline) => (
        <button
          key={outline.idx}
          type="button"
          className="outline"
          aria-label={name(outline)}
          style={place(outline.bbox)}
          data-line={outline.idx}
          onClick={() => onOpen(outline.idx)}
        />
      ))}
    </>
  )
}
