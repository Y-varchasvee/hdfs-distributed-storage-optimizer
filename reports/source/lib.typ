// Shared helpers. Measured values are read from benchmark result files, so the text cannot drift from the data.
#let accent = rgb("#1c5cab")
#let rule-color = rgb("#c3c2b7")
#let muted = rgb("#52514e")

#let results(name) = json("/benchmarks/results/" + name + ".json")
#let MIB = 1048576
#let mib(b, digits: 2) = str(calc.round(b / MIB, digits: digits)) + " MiB"
#let num(v, digits: 2) = str(calc.round(float(v), digits: digits))
#let pct(v, digits: 2) = str(calc.round(float(v), digits: digits)) + "%"
#let size-label(b) = if b == none { "whole file" } else if b < MIB { str(int(b / 1024)) + " KiB" } else { str(int(b / MIB)) + " MiB" }
#let counts = json("generated/test_counts.json")

#let shot(file, caption, width: 100%) = figure(
  box(stroke: 0.5pt + rule-color, image("/screenshots/" + file, width: width)),
  caption: caption,
  kind: image,
)
#let diagram(file, caption, width: 100%) = figure(
  image("/diagrams/" + file, width: width),
  caption: caption,
  placement: auto,
  scope: "parent",
)
#let chart(file, caption, width: 100%, wide: true) = if wide {
  figure(image("/benchmarks/charts/" + file, width: width), caption: caption, placement: auto, scope: "parent")
} else {
  figure(image("/benchmarks/charts/" + file, width: width), caption: caption)
}
#let code(body) = block(fill: rgb("#f7f7f4"), inset: 6pt, radius: 2pt, width: 100%, breakable: true, text(size: 7.5pt, body))
#let placeholder(label) = text(fill: rgb("#b0431c"), "[" + label + "]")

