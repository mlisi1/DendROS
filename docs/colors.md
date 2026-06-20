# Colors

The `color:` field accepts three formats.

---

## Named colors

```yaml
color: "bold blue"
color: "light cyan"
color: "bold light magenta"
```

**Standard names (ANSI 8-color):** `black` `red` `green` `yellow` `blue` `magenta` `cyan` `white`

**Modifiers:**

| Modifier | Effect | Example |
|---|---|---|
| *(none)* | Standard ANSI | `"yellow"` |
| `light` / `bright` | Bright variant (90–97 range) | `"light yellow"` |
| `dark` / `dim` | Dim variant (SGR `;2`) | `"dark yellow"` |
| `bold` | Bold (SGR `;1`) | `"bold yellow"` |

Modifiers can be combined: `"bold light cyan"` → bold + bright cyan.

---

## Extended named colors

These names resolve to 24-bit truecolor automatically — no hex needed.

```yaml
color: "orange"
color: "bold purple"
color: "crimson"
color: "mint"
color: "sky"
```

<table>
  <thead><tr><th>Name</th><th>Color</th><th>Name</th><th>Color</th></tr></thead>
  <tbody>
    <tr><td colspan="4" style="background:none;padding:4px 8px;font-size:.8em;opacity:.6">reds &amp; pinks</td></tr>
    <tr>
      <td><code style="color:#DC143C">crimson</code></td><td><span style="color:#DC143C">deep red</span></td>
      <td><code style="color:#800000">maroon</code></td><td><span style="color:#800000">dark red</span></td>
    </tr>
    <tr>
      <td><code style="color:#FF007F">rose</code></td><td><span style="color:#FF007F">vivid rose</span></td>
      <td><code style="color:#FF69B4">pink</code></td><td><span style="color:#FF69B4">hot pink</span></td>
    </tr>
    <tr>
      <td><code style="color:#FF7F50">coral</code></td><td><span style="color:#FF7F50">coral red</span></td>
      <td><code style="color:#FA8072">salmon</code></td><td><span style="color:#FA8072">soft salmon</span></td>
    </tr>
    <tr><td colspan="4" style="background:none;padding:4px 8px;font-size:.8em;opacity:.6">oranges &amp; yellows</td></tr>
    <tr>
      <td><code style="color:#FFA500">orange</code></td><td><span style="color:#FFA500">warm orange</span></td>
      <td><code style="color:#FFBF00">amber</code></td><td><span style="color:#FFBF00">amber</span></td>
    </tr>
    <tr>
      <td><code style="color:#FFD700">gold</code></td><td><span style="color:#FFD700">golden yellow</span></td>
      <td></td><td></td>
    </tr>
    <tr><td colspan="4" style="background:none;padding:4px 8px;font-size:.8em;opacity:.6">greens</td></tr>
    <tr>
      <td><code style="color:#32CD32">lime</code></td><td><span style="color:#32CD32">lime green</span></td>
      <td><code style="color:#3EB489">mint</code></td><td><span style="color:#3EB489">mint green</span></td>
    </tr>
    <tr>
      <td><code style="color:#808000">olive</code></td><td><span style="color:#808000">dark olive</span></td>
      <td><code style="color:#008080">teal</code></td><td><span style="color:#008080">dark teal</span></td>
    </tr>
    <tr>
      <td><code style="color:#40E0D0">turquoise</code></td><td><span style="color:#40E0D0">bright turquoise</span></td>
      <td></td><td></td>
    </tr>
    <tr><td colspan="4" style="background:none;padding:4px 8px;font-size:.8em;opacity:.6">blues</td></tr>
    <tr>
      <td><code style="color:#87CEEB">sky</code></td><td><span style="color:#87CEEB">sky blue</span></td>
      <td><code style="color:#007FFF">azure</code></td><td><span style="color:#007FFF">bright blue</span></td>
    </tr>
    <tr>
      <td><code style="color:#000080">navy</code></td><td><span style="color:#000080">dark navy</span></td>
      <td></td><td></td>
    </tr>
    <tr><td colspan="4" style="background:none;padding:4px 8px;font-size:.8em;opacity:.6">purples</td></tr>
    <tr>
      <td><code style="color:#967BB6">lavender</code></td><td><span style="color:#967BB6">soft lavender</span></td>
      <td><code style="color:#9370DB">purple</code></td><td><span style="color:#9370DB">medium purple</span></td>
    </tr>
    <tr>
      <td><code style="color:#EE82EE">violet</code></td><td><span style="color:#EE82EE">light violet</span></td>
      <td><code style="color:#C8A2C8">lilac</code></td><td><span style="color:#C8A2C8">soft lilac</span></td>
    </tr>
    <tr>
      <td><code style="color:#4B0082">indigo</code></td><td><span style="color:#4B0082">dark indigo</span></td>
      <td></td><td></td>
    </tr>
    <tr><td colspan="4" style="background:none;padding:4px 8px;font-size:.8em;opacity:.6">neutrals</td></tr>
    <tr>
      <td><code style="color:#A0522D">brown</code></td><td><span style="color:#A0522D">sienna brown</span></td>
      <td><code style="color:#808080">grey</code> / <code style="color:#808080">gray</code></td><td><span style="color:#808080">medium grey</span></td>
    </tr>
  </tbody>
</table>

`bold` works with all extended names (`"bold orange"`, `"bold purple"`, …).
`light` / `dark` modifiers are ignored for extended names — the RGB value is fixed. Use a `#hex` code if you need precise control.

!!! note
    `dark` / `light` modifiers do not apply to hex colors or extended named colors — the RGB value itself sets the brightness.

---

## Hex truecolor

| Syntax | Effect |
|---|---|
| `"#FF6600"` | 24-bit RGB |
| `"@#FF6600"` | Bold + 24-bit RGB |
| `"bold #FF6600"` | Same as above |

```yaml
color: "#CC8800"      # amber
color: "@#00BFFF"     # bold deep sky blue
color: "bold #FF4500" # bold orange-red
```

---

## Raw ANSI SGR codes

```yaml
color: "34;1"   # bold blue  (same as "bold blue")
color: "92"     # bright green  (same as "light green")
```

---

## Preview

<div class="term">
  <div class="term-bar">
    <div class="term-dots">
      <div class="term-dot term-dot-red"></div>
      <div class="term-dot term-dot-yellow"></div>
      <div class="term-dot term-dot-green"></div>
    </div>
    <div class="term-title">color preview</div>
  </div>
  <div class="term-body"><span class="t-blue">[node-1]</span> <span class="t-blue t-badge">[LOC]</span>  bold blue
<span class="t-green">[node-1]</span> <span class="t-green t-badge">[NAV]</span>  bold green
<span class="t-orange">[node-1]</span> <span class="t-orange t-badge">[HW]</span>   orange
<span class="t-cyan">[node-1]</span> <span class="t-cyan t-badge">[SEN]</span>  bold cyan
<span style="color:#9370DB;font-weight:bold">[node-1]</span> <span style="color:#9370DB;font-weight:bold">[AI]</span>   bold purple
<span class="t-dim">[node-1]</span> <span class="t-dim t-badge">[DBG]</span>  dim cyan</div>
</div>
