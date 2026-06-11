// yttranscript - Pandoc Typst template for styled transcript PDFs

#set smartquote(enabled: false)

#set page(
  paper: "a4",
  margin: (top: 2.5cm, bottom: 2.2cm, left: 2.2cm, right: 2.2cm),
  numbering: (n, pages) => {
    set text(size: 8.5pt, fill: luma(140))
    align(center)[#n]
  },
)

#set text(
  size: 10.5pt,
  fill: luma(40),
)

#set par(
  leading: 0.75em,
  justify: true,
  first-line-indent: 0em,
)

#set heading(numbering: none)

#show heading.where(level: 1): it => {
  set text(size: 1.5em, weight: "bold", fill: rgb("#7c3aed"))
  it
  v(0.3em)
}

#show heading.where(level: 2): it => {
  set text(size: 1.15em, weight: "bold", fill: luma(50))
  it
}

#show heading.where(level: 3): it => {
  set text(size: 1.05em, weight: "bold", fill: luma(60))
  it
}

#show link: it => {
  set text(fill: rgb("#7c3aed"))
  it
}

#show raw.where(block: true): it => {
  set text(size: 9pt, font: "New Computer Modern Mono")
  block(
    width: 100%,
    fill: rgb("#f8fafc"),
    stroke: rgb("#e2e8f0"),
    inset: (x: 0.8em, y: 0.5em),
    radius: 3pt,
    it,
  )
}

// --- Title block ---
$if(title)$
#align(center)[
  #block(inset: (bottom: 0.6em))[
    #text(size: 2em, weight: "bold", fill: rgb("#7c3aed"))[$title$]
  ]
]
$endif$

// --- Metadata block ---
$if(url)$
#block(
  width: 100%,
  inset: (x: 1.2em, y: 0.7em),
  fill: rgb("#f8fafc"),
  radius: 5pt,
  stroke: rgb("#e2e8f0"),
)[
  #grid(
    columns: (auto, 1fr),
    column-gutter: 1em,
    row-gutter: 0.35em,
    text(weight: "bold", fill: rgb("#64748b"))[URL:], link("$url$"),
    $if(duration)$text(weight: "bold", fill: rgb("#64748b"))[Duration:], [$duration$],$endif$
    $if(channel)$text(weight: "bold", fill: rgb("#64748b"))[Channel:], [$channel$],$endif$
    $if(upload_date)$text(weight: "bold", fill: rgb("#64748b"))[Upload Date:], [$upload_date$],$endif$
    $if(source)$text(weight: "bold", fill: rgb("#64748b"))[Source:], [$source$],$endif$
  )
]
#v(0.6em)
#line(length: 100%, stroke: rgb("#e2e8f0"))
#v(0.8em)
$endif$

// --- Body ---
$body$
