# Media tools (macOS only)

Small Swift command-line tools used to make the hero film and the photographs in `web/src/assets/media/`.
They use Apple's built-in video and image frameworks, so they need a Mac with the Xcode command-line tools
(`swiftc`). Nothing in the app depends on them; they only produce files.

Build once: `swiftc -O grade.swift -o grade` (and the same for `montage` and `encode`).

| Tool | What it does |
|---|---|
| `grade` | Turns a clip black and white but keeps one object in a brand colour. It keys the object by brightness (`luma`), by "bright and colourless" (`white`, for cloth next to skin) or by its original colour (`hue`), optionally limited to boxes (`region:x0,y0,x1,y1`) and to the foreground subject Apple's Vision finds in each frame (`fg`). Writes a 4K clip, or a single 4K frame when the output ends in `.png`. |
| `montage` | Joins clips end to end (`file:start:duration ...`). |
| `encode` | Re-encodes a clip at a given size and bitrate. |

The settings used for the current film (source clips are listed in `web/src/assets/media/CREDITS.md`):

```
grade v4596.mp4  g1.mp4 9.0 2.4 white:0.16:0.25:0.47:blue:0.62:1.5 region:0.28,0,0.63,0.75     # hand wraps, blue
grade v40765.mp4 g2.mp4 5.6 2.0 luma:0.10:0.20:green:0.62:1.05 fg region:0,0.3,1,1             # running shoes, green
grade v608.mp4   g3.mp4 7.0 3.0 gray
grade v40250.mp4 g4.mp4 3.0 2.2 gray
grade v744.mp4   g5.mp4 5.0 2.0 hue:8:42:0.45:blue                                             # basketball, blue
grade v40881.mp4 g6.mp4 3.5 3.0 gray
montage master.mp4 AVAssetExportPreset3840x2160 g1.mp4:0:2.4 g2.mp4:0:2.0 g3.mp4:0:3.0 g4.mp4:0:2.2 g5.mp4:0:2.0 g6.mp4:0:3.0
encode master.mp4 hero-2160.mp4 3840 2160 10000000
encode master.mp4 hero-1080.mp4 1920 1080 4800000
encode master.mp4 hero-720.mp4  1280 720  2200000
encode master.mp4 hero-480.mp4  854  480  900000
```

Photos: `grade v4596.mp4 wraps.png 12.8 1 white:... region:...` (blue wraps),
`grade v875.mp4 tennis-feet.png 3.3 1 luma:0.07:0.18:green:0.7:1.1 fg region:0.28,0.25,0.44,0.48 region:0.44,0.42,0.6,0.7` (green shoes),
`grade v608.mp4 silhouette.png 10.4 1 gray`.
