# Colors

The `color:` field accepts three formats.

---

## Named colors

```yaml
color: "bold blue"
color: "light cyan"
color: "bold light magenta"
```

**Available names:** `black` `red` `green` `yellow` `blue` `magenta` `cyan` `white`

**Modifiers:**

| Modifier | Effect | Example |
|---|---|---|
| *(none)* | Standard ANSI | `"yellow"` |
| `light` / `bright` | Bright variant (90–97 range) | `"light yellow"` |
| `dark` / `dim` | Dim variant (SGR `;2`) | `"dark yellow"` |
| `bold` | Bold (SGR `;1`) | `"bold yellow"` |

Modifiers can be combined: `"bold light cyan"` → bold + bright cyan.

!!! note
    `dark` / `light` modifiers do not apply to hex colors — the RGB value itself sets the brightness.

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
<span class="t-orange">[node-1]</span> <span class="t-orange t-badge">[HW]</span>   #CC8800
<span class="t-cyan">[node-1]</span> <span class="t-cyan t-badge">[SEN]</span>  bold cyan
<span class="t-dim">[node-1]</span> <span class="t-dim t-badge">[DBG]</span>  dim cyan</div>
</div>
