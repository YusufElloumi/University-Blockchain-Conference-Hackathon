# Media tools (macOS only)

Small Swift command-line tools used to make the hero film and the photographs in `web/src/assets/media/`.
They use Apple's built-in video and image frameworks, so they need a Mac with the Xcode command-line tools
(`swiftc`). Nothing in the app depends on them; they only produce files.

Build once: `swiftc -O grade.swift -o grade` (and the same for `montage` and `encode`).

| Tool | What it does |
|---|---|
| `grade` | Turns a clip black and white but keeps one object in a brand colour, through a hard-edged mask so the colour sits only on that object. It finds the object by brightness (`luma`), by "bright and colourless" (`white`: cloth or snow, not skin or sky) or by its original colour (`hue`). Options clean the mask: `region:` boxes, `fg` (the subject Apple Vision finds in each frame), `bottom:F` (only the lowest part of that subject, e.g. a shoe but not the leg), `close:N` (fill holes so the object is covered evenly), `open:N` (drop specks), `bw:r,g,b` (how colours map to grey; a red-heavy mix darkens blue sky). Writes a 4K clip, or one 4K frame when the output ends in `.png`. The full option list is at the top of `grade.swift`. |
| `montage` | Joins clips end to end (`file:start:duration ...`). |
| `encode` | Re-encodes a clip at a given size and bitrate. |

The settings used for the current film (source clips are listed in `web/src/assets/media/CREDITS.md`):

```
grade v4596.mp4  g1.mp4 9.0 2.4 white:0.17:0.50:blue:0.62:1.5 region:0.33,0,0.63,0.78 close:44 open:18   # hand wraps, blue
grade v40765.mp4 g2.mp4 8.9 1.2 luma:0.10:green:0.62:1.05 fg bottom:0.3 close:90 open:14                # running shoes, green
grade v608.mp4   g3.mp4 7.0 3.4 gray
grade v40250.mp4 g4.mp4 3.0 2.2 gray
grade v744.mp4   g5.mp4 5.0 2.0 hue:8:42:0.45:blue:0.8:1 close:16 open:10                               # basketball, blue
grade v40881.mp4 g6.mp4 3.5 3.4 gray
montage master.mp4 AVAssetExportPreset3840x2160 g1.mp4:0:2.4 g2.mp4:0:1.2 g3.mp4:0:3.4 g4.mp4:0:2.2 g5.mp4:0:2.0 g6.mp4:0:3.4
encode master.mp4 hero-2160.mp4 3840 2160 10000000
encode master.mp4 hero-1080.mp4 1920 1080 4800000
encode master.mp4 hero-720.mp4  1280 720  2200000
encode master.mp4 hero-480.mp4  854  480  900000
```

The shoe shot uses 8.9 to 10.1 seconds of its clip because the foot is found on every frame there; elsewhere in
the clip the second foot crossing the frame makes the colour drop out for a moment. If the film's shot lengths
change, update the chapter times in `web/src/sitekit.tsx` (`CHAPTERS`).

Photos (each is one frame, then saved as a 3840px and a 1920px JPEG):

```
grade v4596.mp4  wraps.png       12.8 1 white:0.17:0.50:blue:0.62:1.5 region:0.27,0.2,0.63,0.78 close:70 open:18
grade v875.mp4   tennis-feet.png  3.3 1 luma:0.07:green:0.7:1.1 fg region:0.28,0.25,0.44,0.48 region:0.44,0.42,0.6,0.7 close:24 open:8
grade v51673.mp4 summit.png      15.0 1 white:0.5:0.13:blue:0.92:1.0 bw:0.95,0.25,-0.2 region:0.2,0,1,1 region:0,0.82,0.2,1 close:7 open:3
```
