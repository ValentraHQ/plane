# Mermaid diagrams

> **Fork-specific (ValentraHQ).** Upstream Plane Community Edition shows Mermaid source as plain code.

Pages (wiki and project pages) and other rich-text editors render [Mermaid](https://mermaid.js.org) diagrams:
flowcharts, sequence, class, state, ER and Gantt diagrams, mind maps and the rest of Mermaid's diagram types.

## Adding a diagram

- Type `/mermaid` (or `/diagram`) and pick **Mermaid diagram**. A starter flowchart is inserted.
- Or type ` ```mermaid ` followed by a space to turn the line into a Mermaid block.
- Pasting Markdown with a ` ```mermaid ` fence also creates one.

## Editing

The block shows the rendered diagram. **Edit** opens the source with a live preview below it; the diagram
re-renders as you type, and syntax errors are shown in the block with Mermaid's message. **Done** hides the
source and puts the cursor below the diagram. The source is also shown whenever the cursor is inside it, so
text is never typed out of sight.

Readers without edit rights see the diagram and can use **Show source**. Diagrams follow the light and dark
themes.

## How it works

A diagram is an ordinary code block whose language is `mermaid`. Nothing new is stored: real-time
collaboration, saved HTML (`<pre><code class="language-mermaid">`), version history and Markdown copy and
paste treat it as code, so pages stay readable in exports and in upstream Plane.

Rendering happens in the browser (`packages/editor/src/extensions/code/mermaid/`). Mermaid is loaded on demand,
only when a page contains a diagram. It runs with `securityLevel: "strict"`, which sanitises the SVG and
disables click handlers and HTML labels, because page content comes from other users.

## Limitations

- PDF export prints the diagram source as code, not the picture.
- Mermaid's interactive features (click links, HTML labels) are off; see above.
