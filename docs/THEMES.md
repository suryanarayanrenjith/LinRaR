# Themes

A theme changes every colour LinRAR draws, the corner radii, the font and all
thirty-nine icons.  Press **Ctrl+Shift+M**, or the palette button on the
toolbar, or the one in the menu bar's corner, to pick one, install one, or take
one out again.

Themes live on the web:

- **<https://linrar.vercel.app/themes>**: ten to download, previewed in full.
- **<https://linrar.vercel.app/create>**: the builder. Pick a dozen colours and
  it derives the other eighty, draws the icon set, warns you about anything that
  came out unreadable, and hands you the file.

## Where they live

    themes/                          beside the application: the drop folder
    ~/.local/share/LinRAR/themes     used instead when the above is not writable
    /usr/share/linrar/themes         installed for every user of the machine

The first of those is **not** in version control and nothing is shipped into it:
it is yours, to put themes in.  LinRAR itself has only the light and dark themes
drawn into it; every other theme is one you downloaded or made.

Whichever of the first two you can write to is the one the Themes window installs
into, and it is searched *last*, so a theme you dropped in beats one installed
machine-wide.

## Adding one

**Drop it into the Themes window**, or into the folder above.  Anything there
that could be a theme is treated as one, so all of these work with no further
ceremony:

    my-theme/theme.json              a folder
    my-theme/inner/theme.json        a folder inside a folder, as zips leave them
    my-theme/anything.json           a folder with one JSON file of any name
    my-theme.linrar-theme            one file: the manifest, or a zip of a folder
    my-theme.theme  my-theme.json    the same, spelled differently

A zip is read **in place**; it does not need unpacking.

## Writing one

    my-theme/
      theme.json          the colours, and everything else
      icons/add.svg       optional: replace individual icons outright
      preview.png         optional

`base` says which built-in theme to start from, and every key you leave out
keeps that theme's value, so a ten-line manifest is a perfectly good theme:

    {
      "name": "My Theme",
      "base": "dark",
      "icon_style": "neon",
      "colors": { "window": "#202430", "sel_bottom": "#C05000" },
      "icons":  { "folder": ["#FFD08A", "#E09A20", "#A06A10"] }
    }

| key | what it does |
|---|---|
| `base` | `"light"` or `"dark"`: the built-in theme yours starts from |
| `colors` | any field of `linrar.ui.theme.Colors`, 82 of them |
| `icons` | any field of `linrar.ui.icons.Ink`; `folder` and friends want a `[light, mid, dark]` triple |
| `icon_style` | `gloss`, `flat`, `neon` or `soft`: how all 39 icons are *drawn* |
| `metrics` | `radius`, `button_radius`, `card_radius`, in pixels; 0 is square, 8 is very round |
| `font` | `family` and `size` (`"9pt"`) |
| `icon_svg` | icon name to SVG source, for artwork of your own |
| `stylesheet` | Qt style sheet, appended last, so it overrides everything else |

Nothing is ever dropped silently.  A mistake becomes a note in the Themes
window saying **where** it is, **what you wrote**, **what belongs there** and
**a line of JSON to paste instead**, with a "did you mean" for a misspelled
name.  A theme with mistakes still loads and uses the parts that were right;
one that cannot load at all is *listed*, under "needs fixing", with the same
detail.  Press **Rescan** after editing.

## Sharing one

Zip the folder and rename it to `my-theme.linrar-theme`.  Dropping that on the
Themes window installs it.  A theme is data, nothing in it is ever executed,
and an archive holding an absolute path, a `..`, a symbolic link or an
implausibly large file is refused outright.
