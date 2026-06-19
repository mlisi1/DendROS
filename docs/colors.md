# Colors

The `color:` field in `dendROS.yaml` accepts three formats.

---

## Named colors

Use a color name with optional modifiers:

```yaml
color: "bold blue"
color: "light cyan"
color: "dark red"
color: "bold light magenta"
```

**Available names:** `black` `red` `green` `yellow` `blue` `magenta` `cyan` `white`

**Modifiers:**

| Modifier | Effect | Example |
|---|---|---|
| *(none)* | Standard ANSI color | `"yellow"` |
| `light` / `bright` | Bright variant (90–97 range) | `"light yellow"` |
| `dark` / `dim` | Dim variant (adds SGR `;2`) | `"dark yellow"` |
| `bold` | Bold (adds SGR `;1`) | `"bold yellow"` |

Modifiers can be combined: `"bold light cyan"` → bold + bright cyan.

---

## Hex truecolor

24-bit RGB colors for precise control. Requires a modern terminal (most are).

| Syntax | Effect |
|---|---|
| `"#FF6600"` | 24-bit RGB color |
| `"@#FF6600"` | Bold + 24-bit RGB (`@` prefix = bold) |
| `"bold #FF6600"` | Same as above |

```yaml
color: "#CC8800"       # orange-ish amber
color: "@#00BFFF"      # bold deep sky blue
color: "bold #FF4500"  # bold orange-red
```

!!! note
    `light` / `dark` modifiers do not apply to hex colors — you control the exact RGB value directly.

---

## Raw ANSI SGR codes

Legacy format, still supported for compatibility:

```yaml
color: "34;1"    # bold blue (same as "bold blue")
color: "92"      # bright green (same as "light green")
color: "35"      # magenta
```

---

## Examples

```yaml
groups:
  localization:
    color: "bold blue"          # named + modifier

  navigation:
    color: "bold light green"   # named + two modifiers

  hardware:
    color: "#CC8800"            # hex truecolor

  sensors:
    color: "@#00CED1"           # bold hex truecolor

  debug_nodes:
    color: "dim cyan"           # named + dim
```
