# Media credits

All footage and stills in this folder come from Mixkit (https://mixkit.co) clips whose page shows the
**Mixkit Stock Video Free License**. Clips under Mixkit's **Restricted License** were deliberately not used
(several good ones were rejected for that reason, including two boxing silhouettes and a jump-rope clip).
Stills are single frames taken from the clips. The licence label on each page was checked on 2026-11-18.

| File | Source clip (page: `https://mixkit.co/free-stock-video/<name>/`) | Source quality |
|---|---|---|
| `hero-2160.mp4`, `hero-1080.mp4`, `hero-720.mp4`, `hero-480.mp4`, `hero-poster.jpg` | A 14.6-second cut of six clips, in order: `man-bandaging-his-hand-before-boxing-4596`, `steps-of-a-person-jogging-outside-40765`, `silhouette-of-a-runner-in-the-city-608`, `man-throwing-barbells-to-the-floor-40250`, `basketball-player-dribbling-ball-744`, `man-and-woman-jogging-together-on-the-street-40881` | 4K, except the barbell shot (1080p, upscaled) |
| `wraps.jpg`, `wraps-4k.jpg` | `man-bandaging-his-hand-before-boxing-4596` | 4K |
| `tennis-feet.jpg`, `tennis-feet-4k.jpg` | `tennis-players-feet-875` | 4K |
| `silhouette.jpg`, `silhouette-4k.jpg` | `silhouette-of-a-runner-in-the-city-608` | 4K |

How it is served: every photo has a 1920px file, and 4K sources also have a 3840px file that only large or
high-density screens download (`srcset` in `Photo`, `web/src/sitekit.tsx`). The film has four sizes; the browser
picks one by screen width, so phones get the 1.6 MB file and only screens wider than 2400px get the 18 MB 4K file.
The files themselves are black and white with one object per shot left in a brand colour: blue hand wraps, green
running shoes and a blue basketball in the film; blue wraps and green tennis shoes in the photos. This was done with
the tools in `scripts/media/` (settings in the README there). The page only adds contrast (`.photo img`, `.film video`
in `styles.css`); it must not apply a grayscale filter, which would remove the colour. The file list and descriptions used by the pages are in `web/src/media.ts`.

On 2026-11-18 the site moved from photographs to drawn graphics outside the hero, so the stills that were no longer shown (barbell, dribble, duo-back, duo-street, pedal, stretch, track-lanes) were removed. Their clips are still in the hero film where listed above.

`../logo-mark.png` and `../favicon.png` were made from the team's own logo artwork (black background removed).
