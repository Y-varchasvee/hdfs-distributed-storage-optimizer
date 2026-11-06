#import "lib.typ": *

#set page(columns: 1, margin: (x: 14mm, top: 16mm, bottom: 16mm))
#show raw.where(block: true): set text(size: 6.4pt)
#show raw.where(block: true): set par(justify: false, leading: 0.5em)

#let groups = json("generated/code_files.json")
#let all-files = groups.map(g => g.files).flatten()

= Complete Source Code

This chapter contains the complete authored source: #all-files.len() files and #all-files.map(f => f.lines).sum() lines. It is not a copy. When this PDF is built, each listing is read directly from the repository file, so the report and the repository cannot diverge. Long lines wrap.

The following are deliberately omitted because they are not authored: dependency directories and lock files (`node_modules`, `.venv`, `package-lock.json`), build output (`.next`), the generated UI primitives in `frontend/components/ui/`, which were created by the shadcn/ui command-line tool (their only change is an import path), and generated data such as benchmark results. The database migration is included.

#for group in groups {
  heading(level: 2, group.title)
  for file in group.files {
    block(above: 1em, below: 0.4em, sticky: true)[
      #text(font: "DejaVu Sans Mono", size: 7.5pt, weight: "bold", file.path)
      #h(1fr) #text(size: 7.5pt, fill: muted)[#file.lines lines]
    ]
    block(width: 100%, inset: (left: 4pt), stroke: (left: 0.5pt + rule-color), breakable: true,
      raw(read("/" + file.path), lang: file.lang, block: true))
  }
}
